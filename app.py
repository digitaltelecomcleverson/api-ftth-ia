import os
import numpy as np
import simplekml
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sklearn.cluster import KMeans
from typing import List

app = FastAPI(title="Motor FTTH IA - Topologia de Ramal")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

TABELA_SPLITTERS = {"1x2": 3.8, "1x4": 7.2, "1x8": 10.5, "1x16": 13.8, "1x32": 17.0}

class Coordenada(BaseModel):
    lat: float
    lng: float

class RequestProjeto(BaseModel):
    olt: Coordenada
    clientes: List[Coordenada]
    n_ctos: int
    splitter_ceo: str
    splitter_cto: str
    potencia_olt: float

@app.get("/")
def read_root():
    return {"status": "Servidor FTTH Online"}

@app.post("/api/v1/calcular")
async def calcular_rede(dados: RequestProjeto):
    try:
        clientes_matriz = np.array([[c.lat, c.lng] for c in dados.clientes])
        
        # 1. IA - Clusterização de CTOs
        kmeans_cto = KMeans(n_clusters=dados.n_ctos, random_state=42, n_init=10)
        kmeans_cto.fit(clientes_matriz)
        ctos_geometria = kmeans_cto.cluster_centers()
        
        # 2. IA - Clusterização de CEOs (1º Nível)
        cap_ceo = int(dados.splitter_ceo.split('x')[1]) 
        n_ceos = max(1, int(np.ceil(dados.n_ctos / cap_ceo)))
        kmeans_ceo = KMeans(n_clusters=n_ceos, random_state=42, n_init=10)
        kmeans_ceo.fit(ctos_geometria)
        ceos_geometria = kmeans_ceo.cluster_centers()
        labels_cto_para_ceo = kmeans_ceo.labels_
        
        # 3. Criação do KML com Pastas Profissionais
        kml = simplekml.Kml(name="Projeto FTTH IA - Organizado")
        
        # Estrutura de Pastas
        fol_backbone = kml.newfolder(name="01. BACKBONE (Tronco)")
        fol_ceos = kml.newfolder(name="02. CAIXAS DE EMENDA (CEO)")
        fol_ctos_root = kml.newfolder(name="03. CAIXAS DE ATENDIMENTO (CTO)")
        fol_cabos_root = kml.newfolder(name="04. CABOS DE DISTRIBUIÇÃO")

        perda_ceo = TABELA_SPLITTERS[dados.splitter_ceo]
        perda_cto = TABELA_SPLITTERS[dados.splitter_cto]

        response_ceos = []
        ceos_obj = [] # Guardar referências para o cálculo de cabos

        # Processamento das CEOs
        for i, coord in enumerate(ceos_geometria):
            ceo_id = i + 1
            # Pasta específica da CEO
            pnt = fol_ceos.newpoint(name=f"CEO {ceo_id:02d} ({dados.splitter_ceo})", coords=[(coord[1], coord[0])])
            pnt.style.iconstyle.icon.href = "http://maps.google.com/mapfiles/kml/shapes/target.png"
            
            # Cabo Tronco (Backbone)
            lin = fol_backbone.newlinestring(name=f"Backbone -> CEO {ceo_id:02d}")
            lin.coords = [(dados.olt.lng, dados.olt.lat), (coord[1], coord[0])]
            lin.style.linestyle.width = 5
            lin.style.linestyle.color = "ff0000ff" # Vermelho

            response_ceos.append({"id": ceo_id, "lat": float(coord[0]), "lng": float(coord[1])})

        response_ctos = []
        # Processar CTOs agrupadas por cada CEO (Topologia de Ramal)
        for i_ceo in range(n_ceos):
            # Filtrar CTOs que pertencem a esta CEO
            indices_ctos_deste_ramal = [i for i, label in enumerate(labels_cto_para_ceo) if label == i_ceo]
            if not indices_ctos_deste_ramal: continue

            # Pastas de Ramal
            fol_ramal_cto = fol_ctos_root.newfolder(name=f"Ramal {i_ceo+1:02d}")
            fol_ramal_cabo = fol_cabos_root.newfolder(name=f"Cabo Ramal {i_ceo+1:02d}")
            
            # Ordenar CTOs por proximidade para criar o caminho sequencial
            coords_ctos_ramal = ctos_geometria[indices_ctos_deste_ramal]
            ceo_coord = ceos_geometria[i_ceo]
            
            # Lógica de Rota: CEO -> CTO 1 -> CTO 2...
            ponto_atual = ceo_coord
            restantes = list(zip(indices_ctos_deste_ramal, coords_ctos_ramal))
            sequencia_rota = []
            
            while restantes:
                # Encontra a CTO mais próxima do ponto atual
                mais_proxima = min(restantes, key=lambda x: np.linalg.norm(x[1] - ponto_atual))
                sequencia_rota.append(mais_proxima)
                ponto_atual = mais_proxima[1]
                restantes.remove(mais_proxima)

            # Desenhar a rota sequencial
            ponto_anterior = ceo_coord
            dist_acumulada_ramal = 0
            
            for idx_seq, (real_idx, cto_coord) in enumerate(sequencia_rota):
                dist_trecho = np.sqrt((cto_coord[0]-ponto_anterior[0])**2 + (cto_coord[1]-ponto_anterior[1])**2) * 111.32
                dist_acumulada_ramal += dist_trecho
                
                dist_olt_ceo = np.sqrt((ceo_coord[0]-dados.olt.lat)**2 + (ceo_coord[1]-dados.olt.lng)**2) * 111.32
                dist_total_fibra = dist_olt_ceo + dist_acumulada_ramal
                
                # Orçamento de Potência
                perda_total = (dist_total_fibra * 0.35) + perda_ceo + perda_cto + 0.8
                potencia_final = dados.potencia_olt - perda_total
                
                # CTO Placemark
                pnt = fol_ramal_cto.newpoint(name=f"CTO {real_idx+1:02d} ({dados.splitter_cto})", coords=[(cto_coord[1], cto_coord[0])])
                pnt.description = f"Sinal: {potencia_final:.2f} dBm\nRamal: {i_ceo+1}\nDistancia OLT: {dist_total_fibra:.2f} km"
                
                # Cabo Sequencial (Barramento)
                lin = fol_ramal_cabo.newlinestring(name=f"Cabo Trecho {idx_seq+1}")
                lin.coords = [(ponto_anterior[1], ponto_anterior[0]), (cto_coord[1], cto_coord[0])]
                lin.style.linestyle.width = 3
                lin.style.linestyle.color = "ff00ff00" # Verde
                
                response_ctos.append({
                    "id": real_idx + 1, "ceo_pai_id": i_ceo + 1, "lat": float(cto_coord[0]), "lng": float(cto_coord[1]),
                    "potencia_dbm": round(potencia_final, 2), "status": "OK" if potencia_final > -25 else "BAIXO"
                })
                ponto_anterior = cto_coord

        return {"status": "sucesso", "ceos": response_ceos, "ctos": response_ctos, "kml_conteudo": kml.kml()}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
