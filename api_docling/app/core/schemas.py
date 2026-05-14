from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# --------------------
# ORÇAMENTO SINTÉTICO
# --------------------
class OrcamentoItem(BaseModel):
    # "meta", "submeta", "item"
    tipo: str = ""
    item: str = ""

    # grupos (meta/submeta)
    descricao: str = ""
    custo_total: Optional[str] = None

    # itens (folha)
    codigo: str = ""
    fonte: str = ""
    especificacao: str = ""
    und: str = ""
    quant: Optional[str] = None
    custo_unitario_sem_bdi: Optional[str] = None
    custo_unitario_com_bdi: Optional[str] = None
    custo_parcial: Optional[str] = None
    filhos: List["OrcamentoItem"] = Field(default_factory=list)


class OrcamentoSintetico(BaseModel):
    descricao: str = ""
    total: Optional[float] = None

    # raízes da árvore
    itens_raiz: List[OrcamentoItem] = Field(default_factory=list)

    # lista “plano” (apenas os números de item, ex: ["9.4", "9.5", ...])
    itens_plano: List[str] = Field(default_factory=list)


OrcamentoItem.model_rebuild()


# --------------------
# COMPOSIÇÕES (ANEXO 3)
# --------------------
class LinhaComposicao(BaseModel):
    codigo: str
    banco: str
    descricao: str = ""
    natureza: str = ""  # ex: Composição / Composição Auxiliar / Insumo
    tipo: Optional[str] = ""  # valor bruto da coluna Tipo da composição (pode ser texto, número ou vazio)
    tipo_status: str = ""
    row_uid: str = ""
    block_uid: str = ""
    page_hint: Optional[int] = None
    row_index_in_block: Optional[int] = None
    und: str = ""
    quant: Optional[float] = None
    valor_unit: Optional[float] = None
    total: Optional[float] = None

    # debug: o parser preenche isso quando banco vem “embutido” no código
    banco_coluna: str = ""

    # campos opcionais para preservar informações especiais (ex.: SICRO)
    detalhes: Dict[str, Any] = Field(default_factory=dict)


class LinhaInsumo(LinhaComposicao):
    pass


class BlocoComposicao(BaseModel):
    # item do orçamento (ex: "9.4") detectado do header ou via mapeamento
    item: str = ""
    principal: LinhaComposicao
    composicoes_auxiliares: List[LinhaComposicao] = Field(default_factory=list)
    insumos: List[LinhaInsumo] = Field(default_factory=list)
    pagina_inicio: Optional[int] = None
    pagina_fim: Optional[int] = None
    paginas: List[int] = Field(default_factory=list)
    detalhes: Dict[str, Any] = Field(default_factory=dict)


class Composicoes(BaseModel):
    # chave padrão: "CODIGO|BANCO"
    principais: Dict[str, BlocoComposicao] = Field(default_factory=dict)

    # catálogo de composições auxiliares detalhadas.
    # Cada auxiliar global é tratada como uma composição completa, com suas
    # próprias composições auxiliares e insumos.
    auxiliares_globais: Dict[str, BlocoComposicao] = Field(default_factory=dict)

    # aliases (ex: "883164|SINAPI" -> "88316|SINAPI")
    aliases_auxiliares: Dict[str, str] = Field(default_factory=dict)



# --------------------
# VALIDAÇÃO / RESPOSTA
# --------------------
class OcorrenciaValidacao(BaseModel):
    codigo: str
    severidade: str  # info | aviso | erro
    categoria: str  # orcamento | composicoes | validacao | sistema
    mensagem: str

    origem: str = ""
    indice_origem: Optional[int] = None
    etapa: str = ""
    item: str = ""
    ref_id: str = ""
    pagina_inicio: Optional[int] = None
    pagina_fim: Optional[int] = None
    linha_original: str = ""
    causa: str = ""
    sugestao: str = ""
    evidencia: Dict[str, Any] = Field(default_factory=dict)


class ResumoValidacao(BaseModel):
    total_ocorrencias: int = 0
    total_erros: int = 0
    total_avisos: int = 0
    total_infos: int = 0
    por_categoria: Dict[str, int] = Field(default_factory=dict)
    por_codigo: Dict[str, int] = Field(default_factory=dict)
    tem_erros: bool = False


class Validacao(BaseModel):
    itens_faltando: List[str] = Field(default_factory=list)
    itens_extras: List[str] = Field(default_factory=list)
    composicoes_nao_associadas_diretamente: List[str] = Field(default_factory=list)
    associacoes_por_indicio: List[Dict[str, Any]] = Field(default_factory=list)

    # saídas compactadas e estruturadas para consumo pelo Lovable
    ocorrencias: List[OcorrenciaValidacao] = Field(default_factory=list)
    resumo: ResumoValidacao = Field(default_factory=ResumoValidacao)

    # legados opcionais: podem ser omitidos no payload final
    avisos: Optional[List[str]] = None
    erros: Optional[List[str]] = None
    divergencias: Optional[List[Dict[str, Any]]] = None


class ParseMeta(BaseModel):
    request_id: str = ""
    parser_version: str = ""
    config_schema_version: str = ""
    processing_time_ms: float = 0.0
    environment: str = ""
    input_metadata: Dict[str, Any] = Field(default_factory=dict)
    performance: Dict[str, Any] = Field(default_factory=dict)
    tipo_enrichment: Dict[str, Any] = Field(default_factory=dict)


class ParseResponse(BaseModel):
    status: str = "ok"
    base_id: str
    orcamento_sintetico: OrcamentoSintetico
    composicoes: Optional[Composicoes] = None
    validacao: Validacao
    meta: ParseMeta = Field(default_factory=ParseMeta)
    documento_correcao: Dict[str, Any] = Field(default_factory=dict)
    tipo_manifest: Dict[str, Any] = Field(default_factory=dict)


# necessário por causa da recursão OrcamentoItem.filhos
OrcamentoItem.model_rebuild()
