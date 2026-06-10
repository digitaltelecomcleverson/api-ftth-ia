from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List
import simplekml
import numpy as np

app = FastAPI(title="Motor FTTH Cascata")

# Habilita CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 1. DEFINIÇÃO DAS CLASSES (Ordem correta: Primeiro as que são usadas dentro das outras)

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

# 2. ROTA DE CALCULO

@app.post("/api/v1/calcular")
async def calcular(dados: RequestProjetoCascata):
    try:
        # Lógica de cálculo aqui
        kml = simplekml.Kml(name="Projeto_FTTH")
        
        # Exemplo de resposta para o seu Frontend
        # Certifique-se de que o log no seu index.html espera exatamente esta estrutura
        resp_ctos = []
        for cto in dados.ctos:
            resp_ctos.append({
                "id": cto.id,
                "pai_tipo": cto.pai_tipo,
                "pai_id": cto.pai_id,
                "cabo_utilizado": "ASU-6FO",
                "fibra_sangrada": "Fibra 1",
                "potencia_dbm": -20.0
            })

        return {
            "ceos": [{"id": c.id, "lat": c.lat, "lng": c.lng} for c in dados.ceos],
            "ctos": resp_ctos,
            "kml_conteudo": kml.kml()
        }
    except Exception as e:
        raise HTTPException(status_code=422, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
