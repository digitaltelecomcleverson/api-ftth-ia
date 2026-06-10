import os
import numpy as np
import simplekml
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sklearn.cluster import KMeans
from typing import List

app = FastAPI(title="Motor de Cálculo FTTH com IA")

# Libera o acesso para que qualquer endereço web (inclusive sua hospedagem frontend) consulte a API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class Coordenada(BaseModel):
    lat: float
    lng: float

class RequestProjeto(BaseModel):
    olt: Coordenada
    clientes: List[Coordenada]
    n_ctos: int
    potencia_olt: float = 4.0

@app.get("/")
def read_root():
    return {"status": "Servidor FTTH Online"}

@app.post("/api/v1/calcular")
async def calcular_rede(dados: RequestProjeto):
    if not dados.clientes:
        raise HTTPException(status_code=400, detail="Adicione clientes no mapa para calcular.")
    
    try:
        # 1. Agrupamento Espacial com IA (K-Means)
        clientes_matriz = np.array([[c.lat, c.lng] for c in dados.clientes])
        n_clusters = min(dados.n_ctos, len(dados.clientes))
        
        kmeans = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
        kmeans.fit(clientes_matriz)
        
        ctos_geometria = kmeans.cluster_centers_
        
        # 2. Geração da Árvore Logística e arquivo KML do Google Earth
        kml = simplekml.Kml(name="Projeto FTTH Gerado por IA")
        
        ctos_calculadas = []
        for i, cto_coord in enumerate(ctos_geometria):
            # Cálculo de distância haversine/euclidiana simplificada para KM
            distancia_km = np.sqrt((cto_coord[0] - dados.olt.lat)**2 + (cto_coord[1] - dados.olt.lng)**2) * 111.32
            
            # Balanço de Potência: Perda cabo (0.35dB/km) + Conectores (0.4dB) + Splitter 1x8 (10.5dB)
            perda_total = (distancia_km * 0.35) + 0.4 + 10.5
            potencia_final = dados.potencia_olt - perda_total
            status_sinal = "ÓTIMO" if potencia_final >= -25.0 else "SINAL FRACO"

            # Inserindo marcador no arquivo KML
            ponto_kml = kml.newpoint(name=f"CTO {i+1:02d}", coords=[(cto_coord[1], cto_coord[0])])
            ponto_kml.description = f"Sinal Técnico: {potencia_final:.2f} dBm\nDistância: {distancia_km:.2f} km"
            
            # Inserindo linha do cabo óptico no KML
            linha_kml = kml.newlinestring(name=f"Cabo Alimentador CTO {i+1:02d}")
            linha_kml.coords = [(dados.olt.lng, dados.olt.lat), (cto_coord[1], cto_coord[0])]

            ctos_calculadas.append({
                "id": i + 1,
                "lat": float(cto_coord[0]),
                "lng": float(cto_coord[1]),
                "distancia_km": round(distancia_km, 2),
                "potencia_dbm": round(potencia_final, 2),
                "status": status_sinal
            })
        
        # Converte o mapa do Google Earth em texto puro KML para o usuário baixar direto pelo navegador
        kml_string = kml.kml()

        return {
            "status": "sucesso",
            "ctos": ctos_calculadas,
            "kml_conteudo": kml_string
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro interno no processamento: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    # Porta padrão exigida pela maioria das hospedagens em nuvem
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)