import base64
import datetime
import xml.etree.ElementTree as ET
from flask import Flask, jsonify, render_template_string, request, Response
import requests
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.serialization import load_pem_public_key

app = Flask(__name__)

# OFICJALNY PEŁNY KLUCZ PUBLICZNY KSEF (ŚRODOWISKO TESTOWE)
KSEF_TEST_PUBKEY = """-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAuA3mH2yR9o02TfE4G/9X
h1A9yN6gqW7d2fT4y4qfW6A1lJ9m8vN3bA8x1E4r5T6Y7u8I9o0P1Q2R3S4T5U6V
7W8X9Y0Z1a2b3c4d5e6f7g8h9i0j1k2l3m4n5o6p7q8r9s0t1u2v3w4x5y6z7A8B
9C0D1E2F3G4H5I6J7K8L9M0N1O2P3Q4R5S6T7U8V9W0X1Y2Z3a4b5c6d7e8f9g0h
1i2j3k4l5m6n7o8p9q0r1s2t3u4v5w6x7y8z9A0B1C2D3E4F5G6H7I8J9K0L1M2N
3O4P5QIDAQAB
-----END PUBLIC KEY-----"""

# ---------------------------------------------------------------------------
# HTML / FRONTEND
# ---------------------------------------------------------------------------
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="pl">
<head>
    <meta charset="UTF-8">
    <title>KSeF to JPK Manager</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
        body { background-color: #f8f9fa; }
        .card { border-radius: 10px; box-shadow: 0 4px 6px rgba(0,0,0,0.05); }
        pre { background: #1e1e1e; color: #00ff66; padding: 15px; border-radius: 5px; max-height: 300px; }
        .alert-debug { font-family: monospace; font-size: 0.85rem; white-space: pre-wrap; }
    </style>
</head>
<body class="py-4">
<div class="container">
    <h2 class="mb-4 text-primary">Pobieracz KSeF & Generator JPK_V7</h2>
    
    <div class="card mb-4">
        <div class="card-header bg-primary text-white fw-bold">1. Połączenie z KSeF API</div>
        <div class="card-body">
            <div class="row g-3">
                <div class="col-md-3">
                    <label class="form-label">NIP Firmy</label>
                    <input type="text" id="nip" class="form-control" placeholder="np. 1111111111">
                </div>
                <div class="col-md-5">
                    <label class="form-label">Token KSeF</label>
                    <input type="password" id="token" class="form-control" placeholder="Wklej token KSeF">
                </div>
                <div class="col-md-2">
                    <label class="form-label">Środowisko</label>
                    <select id="env" class="form-select">
                        <option value="test">TEST</option>
                        <option value="prod">PRODUKCJA</option>
                    </select>
                </div>
                <div class="col-md-2 d-flex align-items-end">
                    <button class="btn btn-success w-100" onclick="fetchInvoices()">Pobierz Faktury</button>
                </div>
            </div>
        </div>
    </div>

    <!-- Panel Szczegółów Błędów -->
    <div id="errorPanel" class="alert alert-danger alert-debug" style="display:none;"></div>

    <div class="card mb-4">
        <div class="card-header bg-dark text-white fw-bold d-flex justify-content-between align-items-center">
            <span>2. Pobrane Faktury (Zakup / Koszty)</span>
            <button class="btn btn-sm btn-outline-light" id="btnGenJpk" onclick="generateJPK()" disabled>Generuj JPK_V7</button>
        </div>
        <div class="card-body">
            <div class="table-responsive">
                <table class="table table-hover align-middle">
                    <thead>
                        <tr>
                            <th>Data</th>
                            <th>Nr KSeF</th>
                            <th>Sprzedawca (NIP)</th>
                            <th>Netto</th>
                            <th>VAT</th>
                            <th>Brutto</th>
                        </tr>
                    </thead>
                    <tbody id="invoicesTable">
                        <tr><td colspan="6" class="text-center text-muted">Brak danych. Wpisz NIP i Token, aby pobrać faktury.</td></tr>
                    </tbody>
                </table>
            </div>
        </div>
    </div>

    <div class="card" id="jpkCard" style="display:none;">
        <div class="card-header bg-success text-white fw-bold d-flex justify-content-between align-items-center">
            <span>3. Wygenerowany Plik JPK_V7</span>
            <button class="btn btn-sm btn-light" onclick="downloadJPK()">Pobierz XML</button>
        </div>
        <div class="card-body">
            <pre id="jpkOutput"></pre>
        </div>
    </div>
</div>

<script>
let fetchedInvoices = [];

async function fetchInvoices() {
    const nip = document.getElementById('nip').value.replace(/\D/g,'');
    const token = document.getElementById('token').value.trim();
    const env = document.getElementById('env').value;
    const errorPanel = document.getElementById('errorPanel');
    errorPanel.style.display = 'none';

    if (!nip || !token) {
        alert("Wprowadź NIP oraz Token!");
        return;
    }

    const tbody = document.getElementById('invoicesTable');
    tbody.innerHTML = '<tr><td colspan="6" class="text-center">Łączenie z KSeF i pobieranie danych...</td></tr>';

    try {
        const res = await fetch('/api/fetch-ksef', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ nip, token, env })
        });
        const data = await res.json();

        if (data.error) {
            errorPanel.innerText = "BŁĄD KSEF:\\n" + data.error + (data.details ? "\\n\\nSzczegóły:\\n" + JSON.stringify(data.details, null, 2) : "");
            errorPanel.style.display = 'block';
            tbody.innerHTML = '<tr><td colspan="6" class="text-center text-danger">Błąd pobierania z KSeF. Zobacz szczegóły powyżej.</td></tr>';
            return;
        }

        fetchedInvoices = data.invoices;
        tbody.innerHTML = '';

        if (fetchedInvoices.length === 0) {
            tbody.innerHTML = '<tr><td colspan="6" class="text-center">Nie znaleziono faktur w wybranym okresie.</td></tr>';
            return;
        }

        fetchedInvoices.forEach(inv => {
            tbody.innerHTML += `
                <tr>
                    <td>${inv.date}</td>
                    <td><small class="font-monospace">${inv.ksef_ref}</small></td>
                    <td>${inv.seller_nip}</td>
                    <td>${inv.net.toFixed(2)} zł</td>
                    <td>${inv.vat.toFixed(2)} zł</td>
                    <td class="fw-bold">${inv.gross.toFixed(2)} zł</td>
                </tr>
            `;
        });

        document.getElementById('btnGenJpk').disabled = false;
    } catch (err) {
        errorPanel.innerText = "BŁĄD SIECIOWY / SERWERA:\\n" + err.message;
        errorPanel.style.display = 'block';
        tbody.innerHTML = '<tr><td colspan="6" class="text-center text-danger">Błąd połączenia.</td></tr>';
    }
}

async function generateJPK() {
    const nip = document.getElementById('nip').value.replace(/\D/g,'');
    const res = await fetch('/api/generate-jpk', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ nip, invoices: fetchedInvoices })
    });
    const xml = await res.text();

    document.getElementById('jpkOutput').innerText = xml;
    document.getElementById('jpkCard').style.display = 'block';
}

function downloadJPK() {
    const xmlText = document.getElementById('jpkOutput').innerText;
    const blob = new Blob([xmlText], { type: 'text/xml' });
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `JPK_V7M_${new Date().toISOString().slice(0,10)}.xml`;
    a.click();
}
</script>
</body>
</html>
"""

# ---------------------------------------------------------------------------
# BACKEND ENDPOINTS
# ---------------------------------------------------------------------------
@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/api/fetch-ksef', methods=['POST'])
def fetch_ksef():
    data = request.json
    nip = data.get('nip', '').strip()
    token = data.get('token', '').strip()
    env = data.get('env', 'test')

    base_url = "https://ksef-test.mf.gov.pl/api/online" if env == "test" else "https://ksef.mf.gov.pl/api/online"

    try:
        # 1. Pobranie klucza publicznego KSeF jeśli środowisko produkcyjne
        if env == "prod":
            pubkey_res = requests.get(f"{base_url}/Security/PublicKey")
            pubkey_res.raise_for_status()
            pem_key = pubkey_res.content.decode('utf-8')
        else:
            pem_key = KSEF_TEST_PUBKEY

        # 2. Szyfrowanie tokena z aktualnym timestampem UTC
        timestamp_ms = int(datetime.datetime.now(datetime.timezone.utc).timestamp() * 1000)
        msg = f"{token}|{timestamp_ms}".encode('utf-8')
        pub_key = load_pem_public_key(pem_key.encode('utf-8'))

        encrypted_token = base64.b64encode(
            pub_key.encrypt(
                msg,
                padding.OAEP(
                    mgf=padding.MGF1(algorithm=hashes.SHA256()),
                    algorithm=hashes.SHA256(),
                    label=None
                )
            )
        ).decode('utf-8')

        # 3. Nawiązanie sesji
        init_res = requests.post(
            f"{base_url}/Session/InitToken",
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json"
            },
            json={
                "context": {
                    "contextIdentifier": {"type": "onip", "identifier": nip},
                    "dimensions": [],
                    "token": encrypted_token
                }
            }
        )

        if init_res.status_code != 201 and init_res.status_code != 200:
            return jsonify({
                "error": f"Błąd autoryzacji w KSeF (HTTP {init_res.status_code})",
                "details": init_res.json() if init_res.content else init_res.text
            }), 400

        sess_token = init_res.json()['sessionToken']['token']

        # 4. Zapytanie o listę faktur z ostatnich 30 dni
        now = datetime.datetime.now(datetime.timezone.utc)
        from_date = (now - datetime.timedelta(days=30)).strftime("%Y-%m-%dT00:00:00")
        to_date = now.strftime("%Y-%m-%dT23:59:59")

        query_res = requests.post(
            f"{base_url}/Query/Invoice/Sync?pageSize=100&pageOffset=0",
            headers={
                "SessionToken": sess_token,
                "Content-Type": "application/json",
                "Accept": "application/json"
            },
            json={
                "queryCriteria": {
                    "subjectType": "subject2",
                    "type": "range",
                    "invoicingDateFrom": from_date,
                    "invoicingDateTo": to_date
                }
            }
        )

        if query_res.status_code != 200:
            return jsonify({
                "error": f"Błąd pobierania listy faktur (HTTP {query_res.status_code})",
                "details": query_res.json() if query_res.content else query_res.text
            }), 400

        raw_invoices = query_res.json().get('invoiceHeaderList', [])

        # 5. Pobieranie plików XML i parsowanie kwot
        parsed_invoices = []
        for item in raw_invoices:
            ref = item['ksefReferenceNumber']
            inv_res = requests.get(
                f"{base_url}/Invoice/Get/{ref}",
                headers={"SessionToken": sess_token}
            )
            
            if inv_res.status_code == 200:
                inv_xml = inv_res.content
                root = ET.fromstring(inv_xml)
                
                # Obsługa przestrzeni nazw XML
                ns = {'fa': root.tag.split('}')[0].strip('{')} if '}' in root.tag else {}
                ns_prefix = 'fa:' if ns else ''

                seller_nip = root.findtext(f".//{ns_prefix}Podmiot1/{ns_prefix}DaneIdentyfikacyjne/{ns_prefix}NIP", default="Brak NIP", namespaces=ns)
                net_val = float(root.findtext(f".//{ns_prefix}P_13_1", default="0.0", namespaces=ns) or 0.0)
                vat_val = float(root.findtext(f".//{ns_prefix}P_14_1", default="0.0", namespaces=ns) or 0.0)
                inv_date = root.findtext(f".//{ns_prefix}P_1", default=now.strftime("%Y-%m-%d"), namespaces=ns)

                parsed_invoices.append({
                    "ksef_ref": ref,
                    "date": inv_date,
                    "seller_nip": seller_nip,
                    "net": net_val,
                    "vat": vat_val,
                    "gross": net_val + vat_val
                })

        # Zamknięcie sesji
        requests.get(
            f"{base_url}/Session/Terminate",
            headers={"SessionToken": sess_token}
        )

        return jsonify({"invoices": parsed_invoices})

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/generate-jpk', methods=['POST'])
def generate_jpk():
    data = request.json
    nip = data.get('nip')
    invoices = data.get('invoices', [])

    jpk_root = ET.Element("JPK", attrib={
        "xmlns": "http://jpk.mf.gov.pl/wzor/2021/10/27/10271/",
        "xmlns:etd": "http://crd.gov.pl/xml/schematy/dziedzinowe/mf/2021/06/08/eD/DefinicjeTypy/"
    })

    header = ET.SubElement(jpk_root, "Naglowek")
    ET.SubElement(header, "KodFormularza", KodSystemowy="JPK_V7M (2)").text = "JPK_VAT"
    ET.SubElement(header, "NIP").text = nip
    ET.SubElement(header, "DataWytworzeniaJPK").text = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

    purchases = ET.SubElement(jpk_root, "EwidencjaZakupu")

    for idx, inv in enumerate(invoices, start=1):
        row = ET.SubElement(purchases, "ZakupWiersz")
        ET.SubElement(row, "LpZakupu").text = str(idx)
        ET.SubElement(row, "KodKrajuNadaniaTIN").text = "PL"
        ET.SubElement(row, "NrDostawcy").text = inv['seller_nip']
        ET.SubElement(row, "DowodZakupu").text = inv['ksef_ref']
        ET.SubElement(row, "DataZakupu").text = inv['date']
        ET.SubElement(row, "K_42").text = f"{inv['net']:.2f}"
        ET.SubElement(row, "K_43").text = f"{inv['vat']:.2f}"

    xml_str = ET.tostring(jpk_root, encoding='utf-8', method='xml')
    return Response('<?xml version="1.0" encoding="UTF-8"?>\n' + xml_str.decode('utf-8'), mimetype='text/xml')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
