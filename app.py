import os
import numpy as np
import simplekml
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sklearn.cluster import KMeans
from typing import List

app = FastAPI(title="Motor FTTH IA - Distribuição Multi-Ramal")

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
    return {"status": "Servidor FTTH Multi-Ramal Online"}

@app.post("/api/v1/calcular")
async def calcular_rede(dados: RequestProjeto):
    if not dados.clientes:
        raise HTTPException(status_code=400, detail="Adicione clientes no mapa.")

    try:
        clientes_matriz = np.array([[float(c.lat), float(c.lng)] for c in dados.clientes], dtype=float)
        num_clientes = len(clientes_matriz)
        
        n_clusters_cto = min(int(dados.n_ctos), num_clientes)
        if n_clusters_cto < 1: n_clusters_cto = 1

        if num_clientes <= n_clusters_cto or num_clientes == 1:
            ctos_geometria = clientes_matriz
        else:
            kmeans_cto = KMeans(n_clusters=n_clusters_cto, random_state=42, n_init=10)
            kmeans_cto.fit(clientes_matriz)
            ctos_geometria = kmeans_cto.cluster_centers_

        # Forçamos 1 CEO centralizada para o cluster local para que ela concentre o Splitter de 1º Nível
        # E distribua os cabos (lados) para as CTOs geograficamente separadas
        num_ctos_geradas = len(ctos_geometria)
        ceos_geometria = np.array([np.mean(ctos_geometria, axis=0)]) 
        
        # O algoritmo agrupa as caixas por direção/proximidade (Lados da Caixa de Emenda)
        capacidade_ceo = int(dados.splitter_ceo.split('x')[1]) 
        qtd_ramais_saida = min(capacidade_ceo, num_ctos_geradas)
        
        if qtd_ramais_saida > 1:
            kmeans_ramal = KMeans(n_clusters=qtd_ramais_saida, random_state=42, n_init=10)
            kmeans_ramal.fit(ctos_geometria)
            labels_cto_para_ramal = kmeans_ramal.labels_
        else:
            labels_cto_para_ramal = np.zeros(num_ctos_geradas, dtype=int)

        kml = simplekml.Kml(name="Projeto FTTH - Distribuição Estrela-Barramento")
        fol_backbone = kml.newfolder(name="01. BACKBONE (Cabo Tronco OLT-CEO)")
        fol_ceos = kml.newfolder(name="02. CAIXA DE EMENDA (CEO com Splitter 1º Nível)")
        fol_ctos_root = kml.newfolder(name="03. CAIXAS DE ATENDIMENTO (CTO)")
        fol_cabos_root = kml.newfolder(name="04. CABOS DE DISTRIBUIÇÃO (Saídas da CEO)")

        perda_ceo = TABELA_SPLITTERS.get(dados.splitter_ceo, 10.5)
        perda_cto = TABELA_SPLITTERS.get(dados.splitter_cto, 10.5)

        # Implantando a CEO Central com o Splitter de 1º Nível
        ceo_coord = ceos_geometria[0]
        dist_olt_ceo = np.sqrt((ceo_coord[0] - dados.olt.lat)**2 + (ceo_coord[1] - dados.olt.lng)**2) * 111.32
        
        pnt_ceo = fol_ceos.newpoint(name=f"CEO 01 ({dados.splitter_ceo})", coords=[(float(ceo_coord[1]), float(ceo_coord[0]))])
        pnt_ceo.description = f"Caixa de Emenda Concentradora\nSplitter de 1º Nível: {dados.splitter_ceo}\nFusões organizadas por ramal de saída."
        
        lin_tronco = fol_backbone.newlinestring(name="Cabo Alimentador Tronco")
        lin_tronco.coords = [(float(dados.olt.lng), float(dados.olt.lat)), (float(ceo_coord[1]), float(ceo_coord[0]))]
        lin_tronco.style.linestyle.width = 5
        lin_tronco.style.linestyle.color = "ff0000ff" # Vermelho

        response_ceos = [{
            "id": 1, "lat": float(ceo_coord[0]), "lng": float(ceo_coord[1]), "dist_olt_km": round(dist_olt_ceo, 2)
        }]

        response_ctos = []
        
        # Varre cada lado/ramal de saída independente da CEO
        for i_ramal in range(qtd_ramais_saida):
            ramal_id = int(i_ramal + 1)
            indices_ctos_deste_ramal = [idx for idx, label in enumerate(labels_cto_para_ramal) if int(label) == i_ramal]
            
            if not indices_ctos_deste_ramal:
                continue

            fol_ramal_cto = fol_ctos_root.newfolder(name=f"Ramal {ramal_id:02d} - Lado {ramal_id}")
            fol_ramal_cabo = fol_cabos_root.newfolder(name=f"Cabo de Distribuição - Lado {ramal_id}")
            
            coords_ctos_ramal = ctos_geometria[indices_ctos_deste_ramal]
            
            # Ordenação de percurso linear para esse LADO específico (vizinho mais próximo partindo da CEO)
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
                
                dist_total_fibra = dist_olt_ceo + dist_acumulada_ramal
                perda_fibra = dist_total_fibra * 0.35
                
                # Orçamento: Perda do Splitter da CEO + Perda do Splitter da CTO + Atenuação do Cabo + Conectores
                perda_total = perda_fibra + perda_ceo + perda_cto + 0.6
                potencia_final = dados.potencia_olt - perda_total
                
                # Adiciona o ponto da CTO no KML
                pnt = fol_ramal_cto.newpoint(name=f"CTO {cto_id_num:02d}", coords=[(float(cto_coord[1]), float(cto_coord[0]))])
                pnt.description = f"Ramal de Saída: {ramal_id}\nFibra designada (Fusão na CEO): Fibra {ramal_id}\nPotência calculada: {potencia_final:.2f} dBm"
                
                # Desenha o cabo saindo da CEO ou ligando na CTO anterior do mesmo lado
                lin = fol_ramal_cabo.newlinestring(name=f"Cabo Distribuição Lado {ramal_id} - Trecho {idx_seq+1}")
                lin.coords = [(float(ponto_anterior[1]), float(ponto_anterior[0])), (float(cto_coord[1]), float(cto_coord[0]))]
                lin.style.linestyle.width = 3
                lin.style.linestyle.color = "ff00ff00" # Verde
                
                response_ctos.append({
                    "id": cto_id_num,
                    "ceo_pai_id": 1,
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
        raise HTTPException(status_code=500, detail=f"Erro interno no motor de cálculo: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
