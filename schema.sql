-- Schema do Banco de Dados — Vigia Público SC (Compatível com SQLite e PostgreSQL)
-- Contém as tabelas limpas, agregações, alertas auditáveis e feedbacks de jornalistas.

CREATE TABLE IF NOT EXISTS emendas_clean (
    id_emenda TEXT PRIMARY KEY,
    parlamentar TEXT NOT NULL,
    partido TEXT,
    valor REAL NOT NULL,
    municipio TEXT NOT NULL,
    municipio_normalizado TEXT NOT NULL,
    codigo_ibge TEXT NOT NULL,
    populacao INTEGER NOT NULL,
    valor_per_capita REAL NOT NULL,
    entidade_beneficiaria TEXT NOT NULL,
    area TEXT NOT NULL,
    data TEXT NOT NULL,
    ano_mes TEXT NOT NULL,
    fornecedor_nome TEXT NOT NULL,
    fornecedor_cnpj TEXT NOT NULL,
    uf_fornecedor TEXT NOT NULL,
    data_abertura_fornecedor TEXT,
    capital_social_fornecedor REAL,
    cnae_fornecedor TEXT,
    status_execucao TEXT NOT NULL,
    fonte_url TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS agregados_parlamentar (
    parlamentar TEXT PRIMARY KEY,
    partido TEXT,
    total_emendas REAL NOT NULL,
    quantidade_emendas INTEGER NOT NULL,
    media_valor REAL NOT NULL,
    principal_area TEXT,
    principal_fornecedor TEXT,
    principal_fornecedor_cnpj TEXT,
    percentual_maior_fornecedor REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS agregados_municipio (
    codigo_ibge TEXT PRIMARY KEY,
    municipio TEXT NOT NULL,
    municipio_normalizado TEXT NOT NULL,
    populacao INTEGER NOT NULL,
    total_recebido REAL NOT NULL,
    quantidade_emendas INTEGER NOT NULL,
    valor_per_capita REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS agregados_fornecedor (
    fornecedor_cnpj TEXT PRIMARY KEY,
    fornecedor_nome TEXT NOT NULL,
    uf_fornecedor TEXT NOT NULL,
    data_abertura TEXT,
    capital_social REAL,
    cnae_principal TEXT,
    total_recebido REAL NOT NULL,
    quantidade_emendas INTEGER NOT NULL,
    parlamentares_distintos INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS cnpj_cache (
    cnpj TEXT PRIMARY KEY,
    razao_social TEXT,
    nome_fantasia TEXT,
    situacao_cadastral TEXT NOT NULL DEFAULT 'Ativa',
    data_situacao_cadastral TEXT,
    motivo_situacao_cadastral TEXT,
    data_abertura TEXT,
    natureza_juridica TEXT,
    natureza_juridica_codigo TEXT,
    capital_social REAL DEFAULT 0.0,
    cnae_principal TEXT,
    cnae_descricao TEXT,
    uf TEXT,
    municipio TEXT,
    fonte_consulta TEXT,
    atualizado_em TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS alertas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tipo TEXT NOT NULL,
    regra TEXT NOT NULL,
    pontuacao REAL NOT NULL,
    parlamentar TEXT NOT NULL,
    municipio TEXT,
    codigo_ibge TEXT,
    valor REAL NOT NULL,
    beneficiario TEXT NOT NULL,
    fornecedor_cnpj TEXT,
    justificativa TEXT NOT NULL,
    dados_contexto TEXT NOT NULL,
    fonte_url TEXT NOT NULL,
    hash_auditoria TEXT NOT NULL,
    data_deteccao TEXT NOT NULL,
    util_count INTEGER NOT NULL DEFAULT 0,
    falso_positivo_count INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS alertas_feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    alerta_id INTEGER NOT NULL,
    avaliacao TEXT NOT NULL,
    comentario TEXT,
    jornalista TEXT,
    criado_em TEXT NOT NULL,
    FOREIGN KEY (alerta_id) REFERENCES alertas(id)
);

-- Índices obrigatórios nos campos de busca (parlamentar, município, CNPJ e pontuação)
CREATE INDEX IF NOT EXISTS idx_emendas_parlamentar ON emendas_clean (parlamentar);
CREATE INDEX IF NOT EXISTS idx_emendas_municipio ON emendas_clean (municipio_normalizado);
CREATE INDEX IF NOT EXISTS idx_emendas_codigo_ibge ON emendas_clean (codigo_ibge);
CREATE INDEX IF NOT EXISTS idx_emendas_cnpj ON emendas_clean (fornecedor_cnpj);
CREATE INDEX IF NOT EXISTS idx_emendas_area ON emendas_clean (area);

CREATE INDEX IF NOT EXISTS idx_agreg_mun_nome ON agregados_municipio (municipio_normalizado);
CREATE INDEX IF NOT EXISTS idx_agreg_forn_cnpj ON agregados_fornecedor (fornecedor_cnpj);

CREATE INDEX IF NOT EXISTS idx_alertas_pontuacao ON alertas (pontuacao DESC);
CREATE INDEX IF NOT EXISTS idx_alertas_parlamentar ON alertas (parlamentar);
CREATE INDEX IF NOT EXISTS idx_alertas_municipio ON alertas (codigo_ibge);
CREATE INDEX IF NOT EXISTS idx_alertas_cnpj ON alertas (fornecedor_cnpj);

CREATE INDEX IF NOT EXISTS idx_cnpj_cache_situacao ON cnpj_cache (situacao_cadastral);
CREATE INDEX IF NOT EXISTS idx_cnpj_cache_natureza ON cnpj_cache (natureza_juridica_codigo);
