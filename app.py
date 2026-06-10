import os
import numpy as np
import simplekml
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Dict

app = FastAPI(title="Motor FTTH - Cascata Estável")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

TABELA_SPLITTERS = {"1x2": 2, "1x4": 4, "1x8": 8, "1x16": 16}
CORES_ANATEL = [
    "Verde", "Amarela", "Branca", "Azul", "Vermelha", "Violeta",
    "Marrom", "Rosa", "Preta", "Cinza", "Laranja", "Aqua"
]

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

@app.post("/api/v1/calcular")
async def calcular_rede_cascata(dados: RequestProjetoCascata):
    try:
        kml = simplekml.Kml(name="Projeto Executivo")
        fol_ceos = kml.newfolder(name="CEOs")
        fol_ctos = kml.newfolder(name="CTOs")
        fol_cabos = kml.newfolder(name="Cabos")

        dict_ctos = {c.id: c for c in dados.ctos}
        dict_ceos = {c.id: c for c in dados.ceos}
        
        # Mapeamento de quem alimenta quem
        filhos: Dict[str, Dict[int, List[int]]] = {"CEO": {c.id: [] for c in dados.ceos}, "CTO": {c.id: [] for c in dados.ctos}}
        for cto in dados.ctos:
            if cto.pai_tipo == "CEO":
                filhos["CEO"][cto.pai_id].append(cto.id)
            else:
                filhos["CTO"][cto.pai_id].append(cto.id)

        contador_fibra = {ceo.id: 1 for ceo in dados.ceos}
        tabela_fusao = {ceo.id: "" for ceo in dados.ceos}
        response_ctos = []

        def processar_arvore(pai_id, pai_tipo, lat_pai, lng_pai, dist_acumulada, ceo_id):
            lista_filhos = filhos[pai_tipo].get(pai_id, [])
            for f_id in lista_filhos:
                cto = dict_ctos[f_id]
                f_num = contador_fibra[ceo_id]
                contador_fibra[ceo_id] += 1
                
                dist = np.sqrt((cto.lat - lat_pai)**2 + (cto.lng - lng_pai)**2) * 111.32
                nova_dist = dist_acumulada + dist
                
                # Cálculo de sinal (simples)
                sinal = dados.potencia_olt - (nova_dist * 0.35 + 21.0)
                
                # Desenhar cabo
                lin = fol_cabos.newlinestring(name=f"Cabo para CTO {cto.id}")
                lin.coords = [(lng_pai, lat_pai), (cto.lng, cto.lat)]
                
                # Tabela de fusão
                cor = CORES_ANATEL[(f_num-1)%12]
                tabela_fusao[ceo_id] += f"<tr><td>{f_num}</td><td>{cor}</td><td>CTO {cto.id}</td></tr>"
                
                response_ctos.append({
                    "id": cto.id, "potencia_dbm": round(sinal, 2), 
                    "cabo_utilizado": "12FO" if f_num > 6 else "6FO",
                    "fibra_sangrada": f"Fibra {f_num} ({cor})"
                })
                
                processar_arvore(cto.id, "CTO", cto.lat, cto.lng, nova_dist, ceo_id)

        for ceo in dados.ceos:
            dist_ceo = np.sqrt((ceo.lat - dados.olt.lat)**2 + (ceo.lng - dados.olt.lng)**2) * 111.32
            processar_arvore(ceo.id, "CEO", ceo.lat, ceo.lng, dist_ceo, ceo.id)
            
            # Adicionar CEO ao KML
            pnt = fol_ceos.newpoint(name=f"CEO {ceo.id}", coords=[(ceo.lng, ceo.lat)])
            pnt.description = f"<table>{tabela_fusao[ceo.id]}</table>"

        return {"status": "sucesso", "ctos": response_ctos, "kml_conteudo": kml.kml()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
