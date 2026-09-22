import base64
import datetime
import xml.etree.ElementTree as ET
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.serialization import load_pem_public_key
from flask import Flask, jsonify, render_template, request
import requests

app = Flask(__name__)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/fetch-ksef", methods=["POST"])
def fetch_ksef():
    data = request.json or {}
    nip = data.get("nip", "").strip()
    token = data.get("token", "").strip()
    env = data.get("env", "test")

    # Ustalenie bazowego URL dla wybranego środowiska
    base_url = (
        "https://ksef-test.mf.gov.pl/api/online"
        if env == "test"
        else "https://ksef.mf.gov.pl/api/online"
    )

    try:
        # 1. Pobranie aktualnego klucza publicznego KSeF jako czysty tekst PEM
        pubkey_res = requests.get(f"{base_url}/Security/PublicKey")
        pubkey_res.raise_for_status()

        pem_key_text = pubkey_res.text.strip()
        # Usunięcie ewentualnych cudzysłowów wokół tekstu PEM
        if pem_key_text.startswith('"') and pem_key_text.endswith('"'):
            pem_key_text = pem_key_text[1:-1]

        pub_key = load_pem_public_key(pem_key_text.encode("utf-8"))

        # 2. Szyfrowanie tokena autoryzacyjnego z timestampem UTC (w ms)
        timestamp_ms = int(
            datetime.datetime.now(datetime.timezone.utc).timestamp() * 1000
        )
        msg = f"{token}|{timestamp_ms}".encode("utf-8")

        encrypted_token = base64.b64encode(
            pub_key.encrypt(
                msg,
                padding.OAEP(
                    mgf=padding.MGF1(algorithm=hashes.SHA256()),
                    algorithm=hashes.SHA256(),
                    label=None,
                ),
            )
        ).decode("utf-8")

        # 3. Nawiązanie sesji w KSeF (Inicjalizacja tokenem)
        init_res = requests.post(
            f"{base_url}/Session/InitToken",
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            json={
                "context": {
                    "contextIdentifier": {"type": "onip", "identifier": nip},
                    "dimensions": [],
                    "token": encrypted_token,
                }
            },
        )

        if init_res.status_code not in (200, 201):
            details = (
                init_res.json()
                if "application/json"
                in init_res.headers.get("Content-Type", "")
                else init_res.text
            )
            return (
                jsonify(
                    {
                        "error": f"Błąd autoryzacji w KSeF (HTTP {init_res.status_code})",
                        "details": details,
                    }
                ),
                400,
            )

        sess_token = init_res.json()["sessionToken"]["token"]

        # 4. Zapytanie o listę faktur zakupowych z ostatnich 30 dni
        now = datetime.datetime.now(datetime.timezone.utc)
        from_date = (now - datetime.timedelta(days=30)).strftime(
            "%Y-%m-%dT00:00:00"
        )
        to_date = now.strftime("%Y-%m-%dT23:59:59")

        query_res = requests.post(
            f"{base_url}/Query/Invoice/Sync?pageSize=100&pageOffset=0",
            headers={
                "SessionToken": sess_token,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            json={
                "queryCriteria": {
                    "subjectType": "subject2",  # subject2 = faktury zakupowe (gdzie podmiot jest nabywcą)
                    "type": "range",
                    "invoicingDateFrom": from_date,
                    "invoicingDateTo": to_date,
                }
            },
        )

        if query_res.status_code != 200:
            details = (
                query_res.json()
                if "application/json"
                in query_res.headers.get("Content-Type", "")
                else query_res.text
            )
            return (
                jsonify(
                    {
                        "error": f"Błąd pobierania listy faktur (HTTP {query_res.status_code})",
                        "details": details,
                    }
                ),
                400,
            )

        raw_invoices = query_res.json().get("invoiceHeaderList", [])

        # 5. Pobranie treści XML dla każdej faktury i odczytanie podstawowych danych
        parsed_invoices = []
        for item in raw_invoices:
            ref = item["ksefReferenceNumber"]
            inv_res = requests.get(
                f"{base_url}/Invoice/Get/{ref}",
                headers={"SessionToken": sess_token},
            )

            if inv_res.status_code == 200:
                inv_xml = inv_res.content
                root = ET.fromstring(inv_xml)

                # Wykrywanie przestrzeni nazw (namespace) XML
                ns = (
                    {"fa": root.tag.split("}")[0].strip("{")}
                    if "}" in root.tag
                    else {}
                )
                ns_prefix = "fa:" if ns else ""

                # Odczyt danych sprzedawcy i kwot
                seller_nip = root.findtext(
                    f".//{ns_prefix}Podmiot1/{ns_prefix}DaneIdentyfikacyjne/{ns_prefix}NIP",
                    default="Brak NIP",
                    namespaces=ns,
                )
                net_val = float(
                    root.findtext(
                        f".//{ns_prefix}P_13_1", default="0.0", namespaces=ns
                    )
                    or 0.0
                )
                vat_val = float(
                    root.findtext(
                        f".//{ns_prefix}P_14_1", default="0.0", namespaces=ns
                    )
                    or 0.0
                )
                inv_date = root.findtext(
                    f".//{ns_prefix}P_1",
                    default=now.strftime("%Y-%m-%d"),
                    namespaces=ns,
                )

                parsed_invoices.append(
                    {
                        "ksef_ref": ref,
                        "date": inv_date,
                        "seller_nip": seller_nip,
                        "net": net_val,
                        "vat": vat_val,
                        "gross": round(net_val + vat_val, 2),
                    }
                )

        # 6. Zamknięcie sesji KSeF
        try:
            requests.get(
                f"{base_url}/Session/Terminate",
                headers={"SessionToken": sess_token},
            )
        except Exception:
            pass

        return jsonify({"invoices": parsed_invoices})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
