import os
import numpy as np
import simplekml
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List

app = FastAPI(title="Motor FTTH - Derivação em Cascata entre CTOs")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

TABELA_SPLITTERS = {"1x2": 2, "1x4": 4, "1x8": 8, "1x16": 16}
CORES_ANATEL = ["Verde", "Amarela", "Branca", "Azul", "Vermelha", "Violeta", "Marrom", "Rosa", "Preta", "Cinza", "Laranja", "Aqua"]

class Coordenada(BaseModel):
    lat: float
    lng: float

class ElementoCascata(BaseModel):
    id: int
    lat: float
    lng: float
    pon_id: int
    pai_tipo: str  # "CEO" ou "CTO"
    pai_id: int    # ID do elemento pai de onde deriva o cabo

class RequestProjetoCascata(BaseModel):
    olt: Coordenada
    ceos: List[ElementoCascata]
    ctos: List[ElementoCascata]
    splitter_ceo: str
    splitter_cto: str
    potencia_olt: float

@app.get("/")
def read_root():
    return {"status": "Motor FTTH Derivação em Cascata Ativo"}

@app.post("/api/v1/calcular")
async def calcular_rede_cascata(dados: RequestProjetoCascata):
    if not dados.ceos:
        raise HTTPException(status_code=400, detail="Implante ao menos uma CEO.")
    if not dados.ctos:
        raise HTTPException(status_code=400, detail="Implante CTOs no mapa.")

    # Validação de Limite PON
    limite_caixas = TABELA_SPLITTERS.get(dados.splitter_ceo, 8)
    for ceo in dados.ceos:
        qtd_ctos = len([c for c in dados.ctos if c.pon_id == ceo.pon_id])
        if qtd_ctos > limite_caixas:
            raise HTTPException(status_code=400, detail=f"A PON {ceo.pon_id} possui {qtd_ctos} CTOs. O limite para o splitter {dados.splitter_ceo} é de {limite_caixas}!")

    try:
        kml = simplekml.Kml(name="Projeto Digital Telecom - Derivação Cascata")
        fol_backbone = kml.newfolder(name="01. BACKBONE (Cabo Alimentador)")
        fol_ceos = kml.newfolder(name="02. CAIXAS DE EMENDA (CEO)")
        fol_ctos_root = kml.newfolder(name="03. CAIXAS DE ATENDIMENTO (CTO)")
        fol_cabos_root = kml.newfolder(name="04. CABOS DE DISTRIBUIÇÃO")

        # 1. Desenha Backbone (OLT -> CEOs)
        dict_ceos = {}
        for ceo in dados.ceos:
            dict_ceos[ceo.id] = ceo
            pnt = fol_ceos.newpoint(name=f"CEO {ceo.id:02d}", coords=[(ceo.lng, ceo.lat)])
            pnt.description = f"<h3>CEO {ceo.id:02d}</h3><p>PON Atendida: PON {ceo.pon_id}</p>"
            
            lin_t = fol_backbone.newlinestring(name=f"Cabo Tronco -> CEO {ceo.id:02d}")
            lin_t.coords = [(dados.olt.lng, dados.olt.lat), (ceo.lng, ceo.lat)]
            lin_t.style.linestyle.width = 5
            lin_t.style.linestyle.color = "ff0000ff"

        # Mapas para controle de distâncias acumuladas e caminhos físicos
        dict_ctos = {c.id: c for c in dados.ctos}
        dist_acumulada_nodos = {} # Guarda a distância total de fibra desde a OLT para cada ID de CTO
        response_ctos = []

        # Para calcular a potência de forma correta, processamos as caixas descendo a árvore de derivações
        # Primeiro calculamos as CTOs ligadas direto na CEO, depois as derivadas delas e assim por diante
        elementos_para_processar = dados.ctos.copy()
        
        # Mapa para descobrir quantas caixas dependem de um cabo (para dimensionar se o cabo é de 6FO ou 12FO)
        def contar_caixas_a_jusante(cto_id):
            filhos = [c for c in dados.ctos if c.pai_tipo == "CTO" and c.pai_id == cto_id]
            total = len(filhos)
            for f in map(lambda x: x.id, filhos):
                total += contar_caixas_a_jusante(f)
            return total

        # Loop de processamento em árvore
        while len(elementos_para_processar) > 0:
            processou_algum = False
            for cto in list(elementos_para_processar):
                
                # Descobre a coordenada do pai de onde o cabo está saindo fisicamente
                pai_lat, pai_lng, dist_base = 0.0, 0.0, 0.0
                
                if cto.pai_tipo == "CEO":
                    if cto.pai_id in dict_ceos:
                        ceo_pai = dict_ceos[cto.pai_id]
                        pai_lat, pai_lng = ceo_pai.lat, ceo_pai.lng
                        dist_base = np.sqrt((ceo_pai.lat - dados.olt.lat)**2 + (ceo_pai.lng - dados.olt.lng)**2) * 111.32
                        processou_algum = True
                else: # O pai é outra CTO
                    if cto.pai_id in dist_acumulada_nodos: # O pai já precisa ter sido calculado antes
                        cto_pai = dict_ctos[cto.pai_id]
                        pai_lat, pai_lng = cto_pai.lat, cto_pai.lng
                        dist_base = dist_acumulada_nodos[cto.pai_id]
                        processou_algum = True
                    else:
                        continue # Pula temporariamente se a CTO pai ainda não foi processada no loop

                if processou_algum:
                    # Calcula distância do lance de poste e acumula
                    dist_lance = np.sqrt((cto.lat - pai_lat)**2 + (cto.lng - pai_lng)**2) * 111.32
                    dist_total_fibra = dist_base + dist_lance
                    dist_acumulada_nodos[cto.id] = dist_total_fibra

                    # Regra de Bitola de Engenharia: Conta a carga de caixas que vão passar por esse cabo adiante
                    carga_subsequente = contar_caixas_a_jusante(cto.id)
                    tipo_cabo = "12FO (ASU-120)" if (carga_subsequente + 1) > 6 else "6FO (ASU-80)"

                    # Orçamento de potência
                    potencia = dados.potencia_olt - ((dist_total_fibra * 0.35) + 10.5 + 10.5 + 0.6)
                    fibra_num = (cto.id % 6) if (cto.id % 6) != 0 else 6
                    cor_fibra = CORES_ANATEL[fibra_num - 1]

                    # HTML Unifilar para o Google Earth
                    html_cto = f"""
                    <div style="font-family:sans-serif; width:300px; color:#333;">
                        <h3 style="background-color:#059669; color:white; padding:6px; margin:0; border-radius:4px 4px 0 0;">📦 DIAGRAMA - CTO {cto.id:02d}</h3>
                        <div style="padding:10px; border:1px solid #ddd; background:#fff; font-size:12px;">
                            <p><b>Porta Ativa:</b> PON {cto.pon_id:02d}</p>
                            <p><b>Cabo Derivado de:</b> {cto.pai_tipo} {cto.pai_id:02d}</p>
                            <p><b>Modelo do Cabo do Trecho:</b> {tipo_cabo}</p>
                            <p style="color:#2563eb; font-weight:bold;">✂️ Sangria de Atendimento: Fibra 0{fibra_num} ({cor_fibra})</p>
                            <p style="color:#4b5563;">Carga total pendurada neste cabo: {carga_subsequente + 1} CTOs</p>
                            <hr style="border:0; border-top:1px solid #eee; margin:6px 0;">
                            <p><b>Sinal Estimado:</b> <span style="color:#16a34a; font-weight:bold;">{potencia:.2f} dBm</span></p>
                        </div>
                    </div>
                    """
                    pnt_cto = fol_ctos_root.newpoint(name=f"PON {cto.pon_id:02d} - CTO {cto.id:02d}", coords=[(cto.lng, cto.lat)])
                    pnt_cto.description = html_cto

                    # Desenha a linha de poste reta perfeita da CTO Pai até a CTO Atual (SEM ZIGUE-ZAGUE)
                    lin_c = fol_cabos_root.newlinestring(name=f"Cabo Lance -> CTO {cto.id:02d}")
                    lin_c.coords = [(pai_lng, pai_lat), (cto.lng, cto.lat)]
                    lin_c.style.linestyle.width = 3
                    lin_c.style.linestyle.color = "ff00ff00" # Verde Distribuição

                    response_ctos.append({
                        "id": cto.id, "lat": cto.lat, "lng": cto.lng, "pon_id": cto.pon_id, 
                        "pai_tipo": cto.pai_tipo, "pai_id": cto.pai_id, "potencia_dbm": round(potencia, 2),
                        "cabo_utilizado": tipo_cabo, "fibra_sangrada": f"Fibra {fibra_num} ({cor_fibra})"
                    })

                    elementosParaProcessar.remove(cto)
            
            if not processou_algum and len(elementos_para_processar) > 0:
                # Break de segurança caso o projetista crie um vínculo órfão (vincular a uma CTO que não existe)
                break

        return {
            "status": "sucesso",
            "ceos": [{"id": c.id, "lat": c.lat, "lng": c.lng, "pon_id": c.pon_id} for c in dados.ceos],
            "ctos": response_ctos,
            "kml_conteudo": kml.kml()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro interno no motor em cascata: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
