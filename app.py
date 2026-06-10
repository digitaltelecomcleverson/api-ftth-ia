import os
import numpy as np
import simplekml
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sklearn.cluster import KMeans
from typing import List

app = FastAPI(title="Motor FTTH IA - Corrigido")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

TABELA_SPLITTERS = {
    "1x2": 3.8,
    "1x4": 7.2,
    "1x8": 10.5,
    "1x16": 13.8,
    "1x32": 17.0
}

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
    # Proteção: Valida se há clientes suficientes
    if not dados.clientes or len(dados.clientes) < dados.n_ctos:
        raise HTTPException(status_code=400, detail="Adicione mais clientes no mapa do que o número de caixas desejadas.")

    try:
        # Extrai as coordenadas puras dos clientes
        clientes_matriz = np.array([[float(c.lat), float(c.lng)] for c in dados.clientes], dtype=float)
        
        # Ajusta dinamicamente caso o usuário peça mais CTOs do que o número real de clientes enviados
        n_clusters_cto = min(int(dados.n_ctos), len(clientes_matriz))
        
        # 1. IA - Nível 2: Posicionamento das CTOs
        kmeans_cto = KMeans(n_clusters=n_clusters_cto, random_state=42, n_init=10)
        kmeans_cto.fit(clientes_matriz)
        
        # CORREÇÃO CRÍTICA: Captura os centros de forma compatível com todas as versões do Scikit-Learn
        if hasattr(kmeans_cto, "cluster_centers_"):
            ctos_geometria = kmeans_cto.cluster_centers_
        else:
            ctos_geometria = kmeans_cto.cluster_centers
            
        # 2. IA - Nível 1: Posicionamento das CEOs
        capacidade_ceo = int(dados.splitter_ceo.split('x')[1]) 
        n_ceos = max(1, int(np.ceil(len(ctos_geometria) / capacidade_ceo)))
        n_clusters_ceo = min(n_ceos, len(ctos_geometria))
        
        kmeans_ceo = KMeans(n_clusters=n_clusters_ceo, random_state=42, n_init=10)
        kmeans_ceo.fit(ctos_geometria)
        
        # Captura os centros da CEO de forma compatível
        if hasattr(kmeans_ceo, "cluster_centers_"):
            ceos_geometria = kmeans_ceo.cluster_centers_
        else:
            ceos_geometria = kmeans_ceo.cluster_centers
            
        labels_cto_para_ceo = kmeans_ceo.labels_
        
        # 3. Geração do Arquivo KML Estruturado
        kml = simplekml.Kml(name="Projeto FTTH IA - Barramento")
        
        fol_backbone = kml.newfolder(name="01. BACKBONE (Cabo Tronco)")
        fol_ceos = kml.newfolder(name="02. CAIXAS DE EMENDA (CEO)")
        fol_ctos_root = kml.newfolder(name="03. CAIXAS DE ATENDIMENTO (CTO)")
        fol_cabos_root = kml.newfolder(name="04. CABOS DE DISTRIBUIÇÃO (Ramais)")

        perda_ceo = TABELA_SPLITTERS.get(dados.splitter_ceo, 10.5)
        perda_cto = TABELA_SPLITTERS.get(dados.splitter_cto, 10.5)

        response_ceos = []
        for i, coord in enumerate(ceos_geometria):
            ceo_id = int(i + 1)
            dist_olt_ceo = np.sqrt((coord[0] - dados.olt.lat)**2 + (coord[1] - dados.olt.lng)**2) * 111.32
            
            pnt = fol_ceos.newpoint(name=f"CEO {ceo_id:02d} ({dados.splitter_ceo})", coords=[(float(coord[1]), float(coord[0]))])
            pnt.description = f"Caixa de Emenda 1º Nível"
            
            lin = fol_backbone.newlinestring(name=f"Backbone -> CEO {ceo_id:02d}")
            lin.coords = [(float(dados.olt.lng), float(dados.olt.lat)), (float(coord[1]), float(coord[0]))]
            lin.style.linestyle.width = 5
            lin.style.linestyle.color = "ff0000ff" # Vermelho

            response_ceos.append({
                "id": ceo_id,
                "lat": float(coord[0]),
                "lng": float(coord[1]),
                "dist_olt_km": round(dist_olt_ceo, 2)
            })

        response_ctos = []
        for i_ceo in range(len(ceos_geometria)):
            ceo_id_atual = int(i_ceo + 1)
            indices_ctos_deste_ramal = [idx for idx, label in enumerate(labels_cto_para_ceo) if int(label) == i_ceo]
            
            if not indices_ctos_deste_ramal:
                continue

            fol_ramal_cto = fol_ctos_root.newfolder(name=f"Ramal {ceo_id_atual:02d} - CTOs")
            fol_ramal_cabo = fol_cabos_root.newfolder(name=f"Cabo Ramal {ceo_id_atual:02d}")
            
            coords_ctos_ramal = ctos_geometria[indices_ctos_deste_ramal]
            ceo_coord = ceos_geometria[i_ceo]
            
            # Ordenação de rota sequencial (Vizinho mais próximo)
            ponto_atual = ceo_coord
            restantes = list(zip(indices_ctos_deste_ramal, coords_ctos_ramal))
            sequencia_rota = []
            
            while restantes:
                mais_proxima = min(restantes, key=lambda x: np.linalg.norm(x[1] - ponto_atual))
                sequencia_rota.append(mais_proxima)
                ponto_atual = mais_proxima[1]
                restantes.remove(mais_proxima)

            ponto_anterior = ceo_coord
            dist_acumulada_ramal = 0.0
            
            for idx_seq, (real_idx, cto_coord) in enumerate(sequencia_rota):
                cto_id_num = int(real_idx + 1)
                
                dist_trecho = np.sqrt((cto_coord[0] - ponto_anterior[0])**2 + (cto_coord[1] - ponto_anterior[1])**2) * 111.32
                dist_acumulada_ramal += dist_trecho
                
                dist_olt_ceo = np.sqrt((ceo_coord[0] - dados.olt.lat)**2 + (ceo_coord[1] - dados.olt.lng)**2) * 111.32
                dist_total_fibra = dist_olt_ceo + dist_acumulada_ramal
                
                perda_fibra = dist_total_fibra * 0.35
                perda_total = perda_fibra + perda_ceo + perda_cto + 0.8
                potencia_final = dados.potencia_olt - perda_total
                
                pnt = fol_ramal_cto.newpoint(name=f"CTO {cto_id_num:02d} ({dados.splitter_cto})", coords=[(float(cto_coord[1]), float(cto_coord[0]))])
                
                lin = fol_ramal_cabo.newlinestring(name=f"Cabo Trecho: CTO {cto_id_num:02d}")
                lin.coords = [(float(ponto_anterior[1]), float(ponto_anterior[0])), (float(cto_coord[1]), float(cto_coord[0]))]
                lin.style.linestyle.width = 3
                lin.style.linestyle.color = "ff00ff00" # Verde
                
                response_ctos.append({
                    "id": cto_id_num,
                    "ceo_pai_id": ceo_id_atual,
                    "lat": float(cto_coord[0]),
                    "lng": float(cto_coord[1]),
                    "potencia_dbm": float(round(potencia_final, 2)),
                    "status": "ÓTIMO" if potencia_final >= -25.0 else "SINAL FRACO"
                })
                ponto_anterior = cto_coord

        return {
            "status": "sucesso",
            "ceos": response_ceos,
            "ctos": response_ctos,
            "kml_conteudo": kml.kml()
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro interno no motor matemático: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
