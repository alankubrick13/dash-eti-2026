# Recursos visuais e certificados

## Marca do Programa Escola em Tempo Integral

`marca/marca_eti.png` é a logo do programa indicada pela coordenação, usada sem alterações no cabeçalho.
Siga o manual (MEC/ACS, v1.0, jan/2024):

- largura de pelo menos 157 px;
- área de proteção ao redor;
- fundo branco;
- nunca recolorir ou distorcer.

Para ocultar a logo, defina `ETI_EXIBIR_MARCA=0`. Se houver uma versão vetorial oficial, salve-a como
`marca/marca_eti.svg`: ela tem prioridade sobre o PNG.

## Tipografia e cores

- **Fonte:** Inter, em `static/fonts/` (licença SIL OFL 1.1, em `static/fonts/OFL.txt`).
- **Paleta:** verde-petróleo `#0E6F7C`, `#4E939C`, `#88B7BD` e `#BAD6DA`, cinza `#C5CBD3` para "nunca
  acessou" e tinta `#1F2933`.

## `estilo.css`

Os ajustes de CSS ficam concentrados neste arquivo. São classes próprias (`eti-*`) e poucos seletores
`data-testid` do Streamlit, testados na versão 1.66.

## `certificados/rnp_icpedu_gr46_ov_tls_ca_2025.pem`

Certificado intermediário público "RNP ICPEdu GR46 OV TLS CA 2025", emitido pela GlobalSign Root R46.

O servidor `download.inep.gov.br` não envia esse intermediário na conexão TLS. Por isso, o download
automático dos microdados falharia com "unable to get local issuer certificate". O painel acrescenta
este arquivo à cadeia de confiança do `certifi`, e a verificação TLS continua completa: o certificado
não substitui nem desativa nada.

- Origem: http://secure.globalsign.com/cacert/rnpicpedugr46ovtlsca2025.crt (endereço indicado no próprio
  certificado do servidor).
- SHA-256: `E1:07:47:D4:DA:7B:AB:09:CB:A9:95:2F:01:9D:35:34:CB:9F:BA:07:0B:F1:3D:87:91:B1:69:9C:D2:FF:59:DD`.
- Validade: até 19/11/2030.
