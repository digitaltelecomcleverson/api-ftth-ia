import os
import numpy as np
import simplekml
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List

app = FastAPI(title="Motor FTTH - Projeto Manual com Sangria ASU 6FO")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

TABELA_SPLITTERS = {"1x2": 3.8, "1x4": 7.2, "1x8": 10.5, "1x16": 13.8, "1x32": 17.0}
CORES_ANATEL = ["Verde", "Amarela", "Branca", "Azul", "Vermelha", "Violeta"]

class Coordenada(BaseModel):
    lat: float
    lng: float

class RequestProjetoManual(BaseModel):
    olt: Coordenada
    ceo: Coordenada
    ctos: List[Coordenada]
    splitter_ceo: str
    splitter_cto: str
    potencia_olt: float

@app.get("/")
def read_root():
    return {"status": "Motor FTTH Manual Ativo"}

@app.post("/api/v1/calcular")
async def calcular_rede_manual(dados: RequestProjetoManual):
    if not dados.ctos:
        raise HTTPException(status_code=400, detail="Adicione pelo menos uma CTO no mapa.")

    try:
        kml = simplekml.Kml(name="Projeto FTTH - Linhas de Sangria Manual")
        fol_backbone = kml.newfolder(name="01. BACKBONE (Cabo Alimentador)")
        fol_ceos = kml.newfolder(name="02. CAIXA DE EMENDA (CEO)")
        fol_ctos_root = kml.newfolder(name="03. CAIXAS DE ATENDIMENTO (CTO)")
        fol_cabos_root = kml.newfolder(name="04. CABOS DE DISTRIBUIÇÃO 6FO")

        perda_ceo = TABELA_SPLITTERS.get(dados.splitter_ceo, 10.5)
        perda_cto = TABELA_SPLITTERS.get(dados.splitter_cto, 10.5)

        # 1. Distância e cabo do Backbone (OLT até a CEO Manual)
        dist_olt_ceo = np.sqrt((dados.ceo.lat - dados.olt.lat)**2 + (dados.ceo.lng - dados.olt.lng)**2) * 111.32
        
        lin_tronco = fol_backbone.newlinestring(name="Cabo Tronco Alimentador")
        lin_tronco.coords = [(dados.olt.lng, dados.olt.lat), (dados.ceo.lng, dados.ceo.lat)]
        lin_tronco.style.linestyle.width = 5
        lin_tronco.style.linestyle.color = "ff0000ff" # Vermelho

        # 2. Separação das CTOs por Lados Geográficos (Vetor de Ângulo em relação à CEO)
        ramal_lado_a = []
        ramal_lado_b = []

        for idx, cto in enumerate(dados.ctos):
            # Calcula o ângulo para descobrir para qual lado da CEO a caixa foi colocada
            dy = cto.lat - dados.ceo.lat
            dx = cto.lng - dados.ceo.lng
            angulo = np.arctan2(dy, dx)
            
            cto_info = {"id": idx + 1, "lat": cto.lat, "lng": cto.lng, "original_obj": cto}
            
            if angulo >= 0:
                ramal_lado_a.append(cto_info)
            else:
                ramal_lado_b.append(cto_info)

        # Ordena as caixas de cada lado pela distância mais próxima partindo da CEO (fluxo contínuo de rua)
        ramal_lado_a.sort(key=lambda c: (c["lat"] - dados.ceo.lat)**2 + (c["lng"] - dados.ceo.lng)**2)
        ramal_lado_b.sort(key=lambda c: (c["lat"] - dados.ceo.lat)**2 + (c["lng"] - dados.ceo.lng)**2)

        ramais_finais = [ramal_lado_a, ramal_lado_b]
        response_ctos = []
        html_ceo_tabela = ""

        # 3. Montagem dos Cabos de Distribuição por Lado com Sangria de Fibra
        for r_idx, ramal in enumerate(ramais_finais):
            if not ramal: continue
            
            nome_ramal = f"Cabo Distribuição 0{r_idx+1} (Lado {'A' if r_idx == 0 else 'B'})"
            html_ceo_tabela += f"<h5>{nome_ramal}</h5><table border='1' cellpadding='3' style='font-size:10px; border-collapse:collapse; width:100%;'>"
            
            pt_anterior_lat = dados.ceo.lat
            pt_anterior_lng = dados.ceo.lng
            dist_acumulada_cabo = 0.0

            for seq_pos, cto in enumerate(ramal):
                # Se passar de 6 caixas em linha, reinicia o contador de fibras do cabo de 6FO
                fibra_idx = seq_pos % 6
                cor_fibra = CORES_ANATEL[fibra_idx]
                
                # Verifica se há uma próxima caixa para detectar derivações ou se é a última
                tem_derivacao = "Não (Fim de Rota)" if seq_pos == len(ramal) - 1 else f"Sim -> Próxima CTO {ramal[seq_pos+1]['id']:02d}"

                # Calcula atenuação da rota
                d_trecho = np.sqrt((cto["lat"] - pt_anterior_lat)**2 + (cto["lng"] - pt_anterior_lng)**2) * 111.32
                dist_acumulada_cabo += d_trecho
                d_total_fibra = dist_olt_ceo + dist_acumulada_cabo
                potencia = dados.potencia_olt - ((d_total_fibra * 0.35) + perda_ceo + perda_cto + 0.6)

                # Documentação HTML Unifilar de cada CTO
                html_cto = f"""
                <div style="font-family:sans-serif; width:300px; color:#333;">
                    <h3 style="background-color:#059669; color:white; padding:6px; margin:0; border-radius:4px 4px 0 0;">📦 DOCUMENTAÇÃO - CTO {cto['id']:02d}</h3>
                    <div style="padding:10px; border:1px solid #ddd; background:#fff; font-size:12px;">
                        <p><b>Origem:</b> {nome_ramal}</p>
                        <p><b>Sequência no Poste:</b> {seq_pos+1}ª Caixa deste cabo</p>
                        <p style="color:#2563eb; font-weight:bold;">✂️ Sangria Óptica: Fibra 0{fibra_idx+1} ({cor_fibra}) ➡️ Ativa no Splitter</p>
                        <p><b>Passante para Derivada:</b> {tem_derivacao}</p>
                        <hr style="border:0; border-top:1px solid #eee; margin:6px 0;">
                        <p><b>Sinal Estimado:</b> <span style="color:#16a34a; font-weight:bold;">{potencia:.2f} dBm</span></p>
                    </div>
                </div>
                """
                
                pnt = fol_ctos_root.newpoint(name=f"CTO {cto['id']:02d}", coords=[(cto["lng"], cto["lat"])])
                pnt.description = html_cto

                # Traçado retilíneo seguindo a ordem de postagem manual
                lin_cabo = fol_cabos_root.newlinestring(name=f"Trecho Cabo {r_idx+1} - CTO {cto['id']:02d}")
                lin_cabo.coords = [(pt_anterior_lng, pt_anterior_lat), (cto["lng"], cto["lat"])]
                lin_cabo.style.linestyle.width = 3
                lin_cabo.style.linestyle.color = "ff00ff00" # Verde Distribuição

                html_ceo_tabela += f"<tr><td>Porta 0{fibra_idx+1}</td><td>Fibra 0{fibra_idx+1} ({cor_fibra})</td><td>➡️ Fusão CTO {cto['id']:02d}</td></tr>"

                response_ctos.append({
                    "id": cto["id"], "lat": cto["lat"], "lng": cto["lng"],
                    "potencia_dbm": round(potencia, 2), "status": "ÓTIMO"
                })
                
                pt_anterior_lat = cto["lat"]
                pt_anterior_lng = cto["lng"]

            html_ceo_tabela += "</table><br>"

        # Atualiza a descrição unifilar da CEO Principal
        html_ceo_completo = f"""
        <div style="font-family:sans-serif; width:340px; color:#333;">
            <h3 style="background-color:#1e3a8a; color:white; padding:8px; margin:0; border-radius:4px 4px 0 0;">📋 UNIFILAR DE EMENDA - CEO 01</h3>
            <div style="padding:10px; border:1px solid #ddd; background:#fff; font-size:12px;">
                <p><b>Splitter 1º Nível alocado:</b> {dados.splitter_ceo}</p>
                <p style="color:#16a34a; font-weight:bold;">🟢 Entrada: Fibra 01 (Verde) do Cabo Tronco ➡️ IN do Splitter</p>
                <hr style="margin:8px 0;">
                {html_ceo_tabela}
            </div>
        </div>
        """
        pnt_ceo = fol_ceos.newpoint(name=f"CEO 01 ({dados.splitter_ceo})", coords=[(dados.ceo.lng, dados.ceo.lat)])
        pnt_ceo.description = html_ceo_completo

        return {
            "status": "sucesso",
            "ceos": [{"id": 1, "lat": dados.ceo.lat, "lng": dados.ceo.lng, "dist_olt_km": round(dist_olt_ceo, 2)}],
            "ctos": response_ctos,
            "kml_conteudo": kml.kml()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro no motor unifilar manual: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
