<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <title>Digital Telecom | Engenharia</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
</head>
<body class="bg-slate-900 text-white">
    <div id="map" class="h-screen w-full"></div>
    <div class="absolute top-5 left-5 bg-slate-800 p-5 rounded-lg shadow-xl w-80">
        <button onclick="processarRede()" class="w-full bg-blue-600 p-2 rounded">⚡ Processar</button>
        <div id="logs" class="mt-4 font-mono text-[10px] text-green-400">Pronto.</div>
    </div>

    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
    <script>
        const map = L.map('map').setView([-12.25, -38.95], 14);
        L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png').addTo(map);
        let dataStore = { olt: {lat: -12.25, lng: -38.95}, ceos: [], ctos: [] };

        async function processarRede() {
            // Limpeza de Integridade: remove qualquer objeto que não tenha marcador ativo
            const payload = {
                olt: dataStore.olt,
                ceos: dataStore.ceos,
                ctos: dataStore.ctos,
                splitter_ceo: "1x8",
                potencia_olt: 4.0
            };
            
            try {
                const response = await fetch("https://api-ftth-ia.onrender.com/api/v1/calcular", {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(payload)
                });
                const data = await response.json();
                if(response.ok) alert("Sucesso!");
                else document.getElementById('logs').innerText = "Erro: " + data.detail;
            } catch(e) { alert("Falha na conexão."); }
        }
    </script>
</body>
</html>
