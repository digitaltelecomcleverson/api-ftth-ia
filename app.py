import os
import numpy as np
import simplekml
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sklearn.cluster import KMeans
from typing import List

app = FastAPI(title="Motor FTTH IA - Documentação Interna KML")

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

# Código de Cores Padrão Anatel para Identificação de Fibras
CORES_ANATEL = ["Verde", "Amarela", "Branca", "Azul", "Vermelha", "Violeta", "Marrom", "Rosa", "Preta", "Cinza", "Laranja", "Aqua"]

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
    return {"status": "Servidor FTTH com Diagrama de Emenda no KML Ativo"}

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

        num_ctos_geradas = len(ctos_geometria)
        ceo_coord = np.mean(ctos_geometria, axis=0)
        
        capacidade_ceo = int(dados.splitter_ceo.split('x')[1]) 
        qtd_ramais_saida = min(capacidade_ceo, num_ctos_geradas)
        
        if qtd_ramais_saida > 1:
            kmeans_ramal = KMeans(n_clusters=qtd_ramais_saida, random_state=42, n_init=10)
            kmeans_ramal.fit(ctos_geometria)
            labels_cto_para_ramal = kmeans_ramal.labels_
        else:
            labels_cto_para_ramal = np.zeros(num_ctos_geradas, dtype=int)

        kml = simplekml.Kml(name="Projeto FTTH - Com Diagrama de Fusão")
        fol_backbone = kml.newfolder(name="01. BACKBONE (Cabo Alimentador)")
        fol_ceos = kml.newfolder(name="02. CAIXA DE EMENDA (CEO)")
        fol_ctos_root = kml.newfolder(name="03. CAIXAS DE ATENDIMENTO (CTO)")
        fol_cabos_root = kml.newfolder(name="04. CABOS DE DISTRIBUIÇÃO")

        perda_ceo = TABELA_SPLITTERS.get(dados.splitter_ceo, 10.5)
        perda_cto = TABELA_SPLITTERS.get(dados.splitter_cto, 10.5)
        dist_olt_ceo = np.sqrt((ceo_coord[0] - dados.olt.lat)**2 + (ceo_coord[1] - dados.olt.lng)**2) * 111.32

        # -----------------------------------------------------------------
        # DOCUMENTAÇÃO DA CEO (DIAGRAMA DE EMENDA INTERNO)
        # -----------------------------------------------------------------
        html_ceo = f"""
        <h3>DIAGRAMA DE EMENDA - CEO 01</h3>
        <p><b>Splitter de 1º Nível instalado:</b> {dados.splitter_ceo}</p>
        <table border="1" cellpadding="5" cellspacing="0" style="border-collapse:collapse; font-family:sans-serif; font-size:12px;">
            <tr style="background-color:#f2f2f2;">
                <th>Origem (Cabo Tronco)</th>
                <th>Elemento Interno</th>
                <th>Destino (Saídas / Ramais)</th>
            </tr>
            <tr>
                <td style="color:green; font-weight:bold;">Fibra 01 (Verde)</td>
                <td>➡️ ENTRADA Splitter {dados.splitter_ceo}</td>
                <td>Distribuição de Sinal Simétrico</td>
            </tr>
        """

        # Mapeamento dinâmico das saídas do splitter para os ramais no HTML da CEO
        for i_ramal in range(qtd_ramais_saida):
            cor_fibra_saida = CORES_ANATEL[i_ramal % len(CORES_ANATEL)]
            html_ceo += f"""
            <tr>
                <td>-</td>
                <td>SAÍDA 0{i_ramal+1} do Splitter</td>
                <td>➡️ Fundida na <b>Fibra 01 ({cor_fibra_saida})</b> do Cabo do <b>Ramal Lado {i_ramal+1}</b></td>
            </tr>
            """
        html_ceo += "</table>"

        pnt_ceo = fol_ceos.newpoint(name=f"CEO 01 ({dados.splitter_ceo})", coords=[(float(ceo_coord[1]), float(ceo_coord[0]))])
        pnt_ceo.description = html_ceo
        
        lin_tronco = fol_backbone.newlinestring(name="Cabo Alimentador Tronco")
        lin_tronco.coords = [(float(dados.olt.lng), float(dados.olt.lat)), (float(ceo_coord[1]), float(ceo_coord[0]))]
        lin_tronco.style.linestyle.width = 5
        lin_tronco.style.linestyle.color = "ff0000ff"

        response_ceos = [{
            "id": 1, "lat": float(ceo_coord[0]), "lng": float(ceo_coord[1]), "dist_olt_km": round(dist_olt_ceo, 2)
        }]

        response_ctos = []
        
        # Geração dos Ramais e das CTOs
        for i_ramal in range(qtd_ramais_saida):
            ramal_id = int(i_ramal + 1)
            cor_do_ramal_na_ceo = CORES_ANATEL[i_ramal % len(CORES_ANATEL)]
            indices_ctos_deste_ramal = [idx for idx, label in enumerate(labels_cto_para_ramal) if int(label) == i_ramal]
            
            if not indices_ctos_deste_ramal:
                continue

            fol_ramal_cto = fol_ctos_root.newfolder(name=f"Ramal Lado {ramal_id} - CTOs")
            fol_ramal_cabo = fol_cabos_root.newfolder(name=f"Cabo Distribuição - Lado {ramal_id}")
            
            coords_ctos_ramal = ctos_geometria[indices_ctos_deste_ramal]
            
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
                perda_total = perda_fibra + perda_ceo + perda_cto + 0.6
                potencia_final = dados.potencia_olt - perda_total
                
                # -----------------------------------------------------------------
                # DOCUMENTAÇÃO DA CTO (IDENTIFICAÇÃO DA FIBRA ATIVA)
                # -----------------------------------------------------------------
                html_cto = f"""
                <h3>DOCUMENTAÇÃO DE ATENDIMENTO - CTO {cto_id_num:02d}</h3>
                <p><b>Ramal Vinculado:</b> Lado {ramal_id}</p>
                <p><b>Origem do Sinal na CEO:</b> Saída 0{ramal_id} do Splitter 1º Nível</p>
                <hr>
                <p><b>Fibra Ativa para Atendimento nesta Caixa:</b> Fibra 01 ({cor_do_ramal_na_ceo}) vinda do ramal.</p>
                <p><b>Splitter de Atendimento:</b> {dados.splitter_cto}</p>
                <p><b>Potência Estimada de Sinal:</b> <span style="color:green; font-weight:bold;">{potencia_final:.2f} dBm</span></p>
                """

                pnt = fol_ramal_cto.newpoint(name=f"CTO {cto_id_num:02d}", coords=[(float(cto_coord[1]), float(cto_coord[0]))])
                pnt.description = html_cto
                
                lin = fol_ramal_cabo.newlinestring(name=f"Cabo Ramal {ramal_id} - Trecho {idx_seq+1}")
                lin.coords = [(float(ponto_anterior[1]), float(ponto_anterior[0])), (float(cto_coord[1]), float(cto_coord[0]))]
                lin.style.linestyle.width = 3
                lin.style.linestyle.color = "ff00ff00"
                
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
