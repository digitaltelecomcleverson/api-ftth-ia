import os
import numpy as np
import simplekml
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List

app = FastAPI(title="Motor FTTH - Cascata Avançada Blindada")

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
    pai_tipo: str  
    pai_id: int    

class RequestProjetoCascata(BaseModel):
    olt: Coordenada
    ceos: List[ElementoCascata]
    ctos: List[ElementoCascata]
    splitter_ceo: str
    splitter_cto: str
    potencia_olt: float

@app.get("/")
def read_root():
    return {"status": "Motor FTTH Cascata Blindado Ativo"}

@app.post("/api/v1/calcular")
async def calcular_rede_cascata(dados: RequestProjetoCascata):
    if not dados.ceos:
        raise HTTPException(status_code=400, detail="Implante ao menos uma Caixa de Emenda (CEO) no mapa.")
    if not dados.ctos:
        raise HTTPException(status_code=400, detail="Implante caixas CTO no mapa antes de processar.")

    # Validação de Limite PON por Splitter
    limite_caixas = TABELA_SPLITTERS.get(dados.splitter_ceo, 8)
    for ceo in dados.ceos:
        qtd_ctos = len([c for c in dados.ctos if c.pon_id == ceo.pon_id])
        if qtd_ctos > limite_caixas:
            raise HTTPException(status_code=400, detail=f"A PON {ceo.pon_id} possui {qtd_ctos} CTOs vinculadas. O splitter {dados.splitter_ceo} suporta no máximo {limite_caixas} caixas!")

    # VALIDAÇÃO CRÍTICA: Verifica integridade da árvore para evitar loops ou IDs inexistentes
    dict_ceos_ids = {c.id for c in dados.ceos}
    dict_ctos_ids = {c.id for c in dados.ctos}

    for cto in dados.ctos:
        if cto.pai_tipo == "CEO" and cto.pai_id not in dict_ceos_ids:
            raise HTTPException(status_code=400, detail=f"Erro de Topologia: A CTO {cto.id} está tentando se conectar à CEO {cto.pai_id}, mas essa CEO não existe no mapa.")
        if cto.pai_tipo == "CTO" and cto.pai_id not in dict_ctos_ids:
            raise HTTPException(status_code=400, detail=f"Erro de Topologia: A CTO {cto.id} está configurada para puxar cabo da CTO {cto.pai_id}, mas essa caixa pai NÃO existe no mapa ainda!")
        if cto.pai_tipo == "CTO" and cto.pai_id == cto.id:
            raise HTTPException(status_code=400, detail=f"Erro de Topologia: A CTO {cto.id} não pode ser pai dela mesma. Escolha outra caixa de origem.")

    try:
        kml = simplekml.Kml(name="Projeto Digital Telecom - Cascata ASU")
        fol_backbone = kml.newfolder(name="01. BACKBONE (Cabo Alimentador)")
        fol_ceos = kml.newfolder(name="02. CAIXAS DE EMENDA (CEO)")
        fol_ctos_root = kml.newfolder(name="03. CAIXAS DE ATENDIMENTO (CTO)")
        fol_cabos_root = kml.newfolder(name="04. CABOS DE DISTRIBUIÇÃO")

        dict_ceos = {c.id: c for c in dados.ceos}
        dict_ctos = {c.id: c for c in dados.ctos}
        dist_acumulada_nodos = {} 
        response_ctos = []

        elementos_para_processar = dados.ctos.copy()
        
        def contar_caixas_a_jusante(cto_id):
            filhos = [c for c in dados.ctos if c.pai_tipo == "CTO" and c.pai_id == cto_id]
            total = len(filhos)
            for f in filhos:
                total += contar_caixas_a_jusante(f.id)
            return total

        tentativas = 0
        max_tentativas = len(elementos_para_processar) * 2

        while len(elementos_para_processar) > 0 and tentativas < max_tentativas:
            tentativas += 1
            for cto in list(elementos_para_processar):
                pai_lat, pai_lng, dist_base = 0.0, 0.0, 0.0
                processou_algum = False
                
                if cto.pai_tipo == "CEO":
                    if cto.pai_id in dict_ceos:
                        ceo_pai = dict_ceos[cto.pai_id]
                        pai_lat, pai_lng = ceo_pai.lat, ceo_pai.lng
                        dist_base = np.sqrt((ceo_pai.lat - dados.olt.lat)**2 + (ceo_pai.lng - dados.olt.lng)**2) * 111.32
                        processou_algum = True
                else:
                    if cto.pai_id in dist_acumulada_nodos:
                        cto_pai = dict_ctos[cto.pai_id]
                        pai_lat, pai_lng = cto_pai.lat, cto_pai.lng
                        dist_base = dist_acumulada_nodos[cto.pai_id]
                        processou_algum = True

                if processou_algum:
                    dist_lance = np.sqrt((cto.lat - pai_lat)**2 + (cto.lng - pai_lng)**2) * 111.32
                    dist_total_fibra = dist_base + dist_lance
                    dist_acumulada_nodos[cto.id] = dist_total_fibra

                    carga_subsequente = contar_caixas_a_jusante(cto.id)
                    tipo_cabo = "12FO (ASU-120)" if (carga_subsequente + 1) > 6 else "6FO (ASU-80)"

                    potencia = dados.potencia_olt - ((dist_total_fibra * 0.35) + 10.5 + 10.5 + 0.6)
                    fibra_num = (cto.id % 6) if (cto.id % 6) != 0 else 6
                    cor_fibra = CORES_ANATEL[fibra_num - 1]

                    html_cto = f"""
                    <div style="font-family:sans-serif; width:300px; color:#333;">
                        <h3 style="background-color:#059669; color:white; padding:6px; margin:0; border-radius:4px 4px 0 0;">📦 DIAGRAMA - CTO {cto.id:02d}</h3>
                        <div style="padding:10px; border:1px solid #ddd; background:#fff; font-size:12px;">
                            <p><b>Porta Ativa:</b> PON {cto.pon_id:02d}</p>
                            <p><b>Cabo Derivado de:</b> {cto.pai_tipo} {cto.pai_id:02d}</p>
                            <p><b>Modelo do Cabo do Trecho:</b> {tipo_cabo}</p>
                            <p style="color:#2563eb; font-weight:bold;">✂️ Sangria de Atendimento: Fibra 0{fibra_num} ({cor_fibra})</p>
                            <p>Carga a jusante: {carga_subsequente} caixas</p>
                            <hr style="border:0; border-top:1px solid #eee; margin:6px 0;">
                            <p><b>Sinal Estimado:</b> <b>{potencia:.2f} dBm</b></p>
                        </div>
                    </div>
                    """
                    pnt_cto = fol_ctos_root.newpoint(name=f"PON {cto.pon_id:02d} - CTO {cto.id:02d}", coords=[(cto.lng, cto.lat)])
                    pnt_cto.description = html_cto

                    lin_c = fol_cabos_root.newlinestring(name=f"Cabo Lance -> CTO {cto.id:02d}")
                    lin_c.coords = [(pai_lng, pai_lat), (cto.lng, cto.lat)]
                    lin_c.style.linestyle.width = 3
                    lin_c.style.linestyle.color = "ff00ff00"

                    response_ctos.append({
                        "id": cto.id, "lat": cto.lat, "lng": cto.lng, "pon_id": cto.pon_id, 
                        "pai_tipo": cto.pai_tipo, "pai_id": cto.pai_id, "potencia_dbm": round(potencia, 2),
                        "cabo_utilizado": tipo_cabo, "fibra_sangrada": f"Fibra {fibra_num} ({cor_fibra})"
                    })
                    elementos_para_processar.remove(cto)

        # Desenha as CEOs no KML final externo
        for ceo in dados.ceos:
            pnt_ceo = fol_ceos.newpoint(name=f"CEO {ceo.id:02d}", coords=[(ceo.lng, ceo.lat)])
            pnt_ceo.description = f"<h3>CEO {ceo.id:02d}</h3><p>PON: {ceo.pon_id}</p>"
            
            lin_t = fol_backbone.newlinestring(name=f"Cabo Tronco -> CEO {ceo.id:02d}")
            lin_t.coords = [(dados.olt.lng, dados.olt.lat), (ceo.lng, ceo.lat)]
            lin_t.style.linestyle.width = 5
            lin_t.style.linestyle.color = "ff0000ff"

        return {
            "status": "sucesso",
            "ceos": [{"id": c.id, "lat": c.lat, "lng": c.lng, "pon_id": c.pon_id} for c in dados.ceos],
            "ctos": response_ctos,
            "kml_conteudo": kml.kml()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro no processamento interno da malha: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
