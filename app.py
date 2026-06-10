import os
import numpy as np
import simplekml
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Dict

app = FastAPI(title="Motor FTTH - Engenharia de Sangria e Unifilar Digital Telecom")

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

@app.get("/")
def read_root():
    return {"status": "Motor de Emendas Estrito Digital Telecom Ativo"}

@app.post("/api/v1/calcular")
async def calcular_rede_cascata(dados: RequestProjetoCascata):
    if not dados.ceos:
        raise HTTPException(status_code=400, detail="Implante ao menos uma CEO no mapa.")
    if not dados.ctos:
        raise HTTPException(status_code=400, detail="Implante caixas CTO no mapa antes de processar.")

    limite_caixas = TABELA_SPLITTERS.get(dados.splitter_ceo, 8)
    
    # Validação de teto físico da porta PON
    for ceo in dados.ceos:
        qtd_ctos = len([c for c in dados.ctos if c.pon_id == ceo.pon_id])
        if qtd_ctos > limite_caixas:
            raise HTTPException(status_code=400, detail=f"A PON {ceo.pon_id} possui {qtd_ctos} CTOs. O limite para o splitter {dados.splitter_ceo} é de {limite_caixas} caixas!")

    try:
        kml = simplekml.Kml(name="Projeto Executivo - Digital Telecom")
        fol_backbone = kml.newfolder(name="01. BACKBONE (Cabo Alimentador)")
        fol_ceos = kml.newfolder(name="02. CAIXAS DE EMENDA (CEO)")
        fol_ctos_root = kml.newfolder(name="03. CAIXAS DE ATENDIMENTO (CTO)")
        fol_cabos_root = kml.newfolder(name="04. CABOS DE DISTRIBUIÇÃO")

        dict_ceos = {c.id: c for c in dados.ceos}
        dict_ctos = {c.id: c for c in dados.ctos}
        
        # Cria estrutura de árvore para navegação hierárquica limpa
        adjacencia_ctos: Dict[int, List[int]] = {c.id: [] for c in dados.ctos}
        filhos_diretos_ceo: Dict[int, List[int]] = {c.id: [] for c in dados.ceos}
        
        for cto in dados.ctos:
            if cto.pai_tipo == "CEO":
                if cto.pai_id in filhos_diretos_ceo:
                    filhos_diretos_ceo[cto.pai_id].append(cto.id)
            else:
                if cto.pai_id in adjacencia_ctos:
                    adjacencia_ctos[cto.pai_id].append(cto.id)

        dist_acumulada_nodos = {}
        fibra_atribuida_cto = {}
        tabela_emendas_master = {ceo.id: "" for ceo in dados.ceos}
        contador_fibra_global = {ceo.id: 1 for ceo in dados.ceos}
        response_ctos = []

        # Função recursiva estruturada para varrer a árvore fixando as fibras na sequência exata Anatel
        def navegar_e_calcular(id_nodo: int, tipo_pai: str, pai_id_num: int, lat_pai: float, lng_pai: float, dist_base: float, ceo_origem_id: int):
            cto = dict_ctos[id_nodo]
            
            # 1. Garante atribuição única e sequencial da fibra vinda da CEO
            f_num = contador_fibra_global[ceo_origem_id]
            contador_fibra_global[ceo_origem_id] += 1
            fibra_atribuida_cto[cto.id] = f_num

            # 2. Orçamento de potência com base na distância de lançamento real
            dist_lance = np.sqrt((cto.lat - lat_pai)**2 + (cto.lng - lng_pai)**2) * 111.32
            total_dist_rota = dist_base + dist_lance
            dist_acumulada_nodos[cto.id] = total_dist_rota

            # 3. Descobre a carga subsequente para saber se usa cabo de 6FO ou 12FO
            def mapear_carga(nid):
                filhos = adjacencia_ctos.get(nid, [])
                sub_tot = len(filhos)
                for fid in filhos:
                    sub_tot += mapear_carga(fid)
                return sub_tot
            
            total_caixas_no_cabo = mapear_carga(
