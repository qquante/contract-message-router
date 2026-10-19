> Historical project notes. Paths, operational status, badges and test claims below are retained as archival reference and have not all been revalidated. Use the root README and docs/REVIEW.md for this review snapshot.

# Telegram Token Forwarder

Monitora mensagens novas publicadas pelos canais `@kenjihl` e
`@cyberleek_io_io`, extrai um unico contrato valido e envia **somente o endereco literal** para
`@helenus_trojanbot`.

O programa nao clica em botoes, nao confirma compras e nao envia ordens. Ele
tambem ignora mensagens do bot de destino para evitar loops.

Apos cada envio confirmado, o Windows toca 8 beeps de 8 segundos a 888 Hz,
separados por 250 ms. O som roda em uma thread propria e nao bloqueia o listener.
Os valores podem ser ajustados pelas variaveis `BEEP_*` do `.env`. A unidade da
frequencia e Hz; 888 MHz nao e uma frequencia audivel.

## Instalar no Windows

```powershell
cd C:\Users\PC\Desktop\telegram
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

Preencha `TELEGRAM_API_ID` e `TELEGRAM_API_HASH` no arquivo `.env`. Essas
credenciais sao obtidas em <https://my.telegram.org/apps>. Nao compartilhe o
arquivo `.env`, o codigo de login, a senha 2FA nem os arquivos `.session`.

Antes do primeiro envio, abra `@helenus_trojanbot` manualmente na conta
`@kenjihl` e pressione **Start**.

## Validar sem conectar

```powershell
.\.venv\Scripts\python.exe -m token_forwarder --check-config
.\.venv\Scripts\python.exe -m token_forwarder --extract "CA: COLE_O_CONTRATO"
.\.venv\Scripts\python.exe -m pytest
```

## Primeiro login e dry-run

Mantenha `DRY_RUN=true` no `.env` e execute:

```powershell
.\.venv\Scripts\python.exe -m token_forwarder
```

No primeiro uso, o Telegram pedira telefone, codigo de login e possivelmente a
senha 2FA. Esses dados devem ser digitados somente no terminal local. Envie uma
nova mensagem de teste contendo um contrato no canal `@kenjihl` e confirme no
log a linha `DRY_RUN contrato detectado`.

Depois, pare com `Ctrl+C`, altere para `DRY_RUN=false` e execute novamente.

Com a sessao ja autorizada e `DRY_RUN=false`, o inicio diario pode ser feito por:

```powershell
.\start.cmd
```

O arquivo `.data/kenjihl.session` guarda a autorizacao local. Nao compartilhe,
copie para terceiros nem publique esse arquivo: quem obtiver a sessao pode ter
acesso a conta do Telegram.

## Regras de seguranca e roteamento

- `SOURCE_CHATS=@kenjihl,@cyberleek_io_io`: aceita somente posts novos desses
  canais.
- `ALLOW_ANY_PRIVATE_SOURCE=false`: impede que mensagens privadas aleatorias
  sejam encaminhadas ao bot.
- `EXPECTED_ACCOUNT_USERNAME` identifica a conta pessoal autenticada, nao o
  canal. Pode ficar vazio; se preenchido, o programa bloqueia uma conta errada.
- Se uma mensagem tiver zero contratos, ela sera ignorada.
- Se uma mensagem tiver mais de um contrato diferente, ela sera ignorada por
  ambiguidade.
- O banco SQLite em `.data/forwarder.sqlite3` impede reenvio do mesmo evento.
- `CONTRACT_NETWORK=auto` reconhece enderecos Solana e EVM. Restrinja para
  `solana` ou `evm` se souber a rede.
- Somente mensagens novas sao processadas; nao ha varredura do historico.
- O alerta toca somente depois de um envio real bem-sucedido; `DRY_RUN` nao toca.

## Wallet Guard: transferencias nativas

O pacote `wallet_guard` e separado do listener Telegram. O escopo atual e apenas
a moeda nativa de cada rede; ERC-20/BEP-20 nao entram no trigger. As redes
permitidas sao Ethereum, Stable, Base, BNB Smart Chain, Robinhood Chain,
Arbitrum One, HyperEVM e Avalanche C-Chain. Unichain nao faz parte da allowlist.

Copie para o `.env` somente o bloco `WALLET_GUARD_*` do `.env.example` e preencha
o endereco publico de origem, o unico destino protegido, o proxy global e um RPC
HTTPS por rede. Nunca coloque seed phrase, chave privada ou senha do keystore no
`.env.example`. Se optar pela chave simples no `.env`, mantenha o arquivo local,
fora do Git e restrito ao usuario do Windows.

O `.env.example` inclui RPCs publicos para o preflight. Eles podem aplicar rate
limit e nao oferecem SLA; para resgate real, use RPCs dedicados e redundantes.

| Rede | RPC incluido | Chain ID | Nativo |
| --- | --- | ---: | --- |
| Ethereum | PublicNode | 1 | ETH |
| Stable | `rpc.stable.xyz` | 988 | USDT0 |
| Base | `mainnet.base.org` | 8453 | ETH |
| BNB Smart Chain | `bsc-dataseed.bnbchain.org` | 56 | BNB |
| Robinhood Chain | `rpc.mainnet.chain.robinhood.com` | 4663 | ETH |
| Arbitrum One | `arb1.arbitrum.io/rpc` | 42161 | ETH |
| HyperEVM | `rpc.hyperliquid.xyz/evm` | 999 | HYPE |
| Avalanche C-Chain | `api.avax.network/ext/bc/C/rpc` | 43114 | AVAX |

Comandos de verificacao e preparacao:

```powershell
.\.venv\Scripts\python.exe -m wallet_guard --check-config
.\.venv\Scripts\python.exe -m wallet_guard --check-private-key
.\.venv\Scripts\python.exe -m wallet_guard --test-mainnet-signatures
.\.venv\Scripts\python.exe -m wallet_guard --preflight --native-only
.\.venv\Scripts\python.exe -m wallet_guard --prepare-native
.\.venv\Scripts\python.exe -m wallet_guard --retry-self-test
```

Todos sao sem broadcast. Apenas `--test-mainnet-signatures` assina bytes
deliberadamente nao executaveis e permanece totalmente offline; os demais nao
assinam.

`--check-private-key` e estritamente offline: deriva somente o endereco publico,
compara com `WALLET_GUARD_SOURCE_WALLET` e nao assina nem acessa RPC. A chave e
lida de `WALLET_GUARD_PRIVATE_KEY` e nunca e exibida no output.

`--test-mainnet-signatures` usa os `chainId` reais configurados, mas assina apenas
transacoes locais nao executaveis (`gas=0`, `value=0`, destino igual a origem).
Os bytes assinados nao sao exibidos, salvos nem enviados a um RPC.

`--prepare-native` valida o `chainId`, codigo de origem/destino, saldo, nonce e
gas; escolhe EIP-1559 ou legacy; reserva taxa conservadora; calcula o valor
enviavel; e repete a estimativa final. Na Base tambem consulta o GasPriceOracle e
reserva o limite superior da taxa L1 com margem. Isso continua sendo uma
transferencia nativa normal de uma carteira para outra.

Todas as redes iniciam em paralelo, com cliente e retry independentes. Timeout,
falha de conexao, HTTP 429 e HTTP 5xx recebem ate exatamente 10 tentativas por
rede. Enderecos aparecem mascarados e credenciais do proxy nao sao impressas.

Origens com bytecode de contrato comum sao recusadas. O formato exato EIP-7702
(`0xef0100` seguido de 20 bytes) e aceito como EOA delegada e recebe aviso no
relatorio. O destino precisa ser uma carteira normal sem bytecode.

O CLI permanece fail-closed: `WALLET_GUARD_DRY_RUN=true`, assinatura desativada e
broadcast desativado. O executor mainnet existe, mas exige simultaneamente as
tres flags de execucao, as oito redes e uma confirmacao literal. O broadcast
reenvia os mesmos bytes por ate 10 tentativas, exige receipt `status=1` e nunca
altera taxa/nonce silenciosamente.

Comando real, para ser usado somente quando a execucao for autorizada:

```powershell
.\.venv\Scripts\python.exe -m wallet_guard --execute-native `
  --confirm-mainnet SEND_NATIVE_BALANCES
```

Enquanto `WALLET_GUARD_DRY_RUN=true`, `WALLET_GUARD_SIGNING_ENABLED=false` e
`WALLET_GUARD_BROADCAST_ENABLED=false`, esse comando e bloqueado antes de criar
cliente RPC ou assinatura. Quando habilitado conscientemente, as oito redes
executam em paralelo e o terminal mostra fase, hash, tentativa, receipt, valor,
saldo restante, bloco, explorer e um resumo final por rede.

O cliente de leitura bloqueia qualquer metodo de escrita. O cliente de broadcast
restrito permite somente `eth_sendRawTransaction` e
`eth_getTransactionReceipt`. Com `WALLET_GUARD_REQUIRE_PROXY=true`, todas as
redes usam exatamente o mesmo proxy e conexao direta e recusada.

A revisao por rede, particularidades de taxa e links oficiais esta em
[`docs/WALLET_GUARD_NETWORK_REVIEW.md`](docs/WALLET_GUARD_NETWORK_REVIEW.md).
