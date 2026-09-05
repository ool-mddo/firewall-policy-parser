# firewall-policy-parser

Juniper SRX のコンフィグファイルから Firewall policy 情報を抽出し、
機械処理可能な JSON 形式で保存する REST API サービス。

ネットワーク機器のコンフィグが混在するディレクトリから SRX の設定ファイルを
自動検出し、TTP (Template Text Parser) でパースして構造化データを出力する。
[bgp-policy-parser](https://github.com/ool-mddo/bgp-policy-parser) と同様の
アーキテクチャに基づいて設計されている。

## 対象機器

- Juniper SRX (JunOS 階層型コンフィグ形式、`display inheritance` 出力)
- SRX cluster の node0/node1 は個別ノードとして扱う

## 抽出対象

| セクション | 抽出内容 |
|---|---|
| `security > policies` | from-zone / to-zone ごとのポリシールール (name, match, action) |
| `security > zones` | ゾーン名 と 所属インタフェース一覧 |

## 出力 JSON 構造

```json
{
  "node": "site-a-fw-1",
  "pair": { "primary": "site-a-fw-1", "secondary": "site-a-fw-2" },
  "policies": [
    {
      "from_zone": "trust",
      "to_zone": "untrust",
      "rules": [
        {
          "name": "default-permit",
          "source_address": "any",
          "destination_address": "any",
          "application": "any",
          "action": "permit"
        }
      ]
    }
  ],
  "zones": [
    { "name": "trust", "interfaces": [] },
    { "name": "WAN",   "interfaces": ["ge-0/0/1.0", "ge-7/0/1.0"] }
  ]
}
```

## ディレクトリ構成

```
firewall-policy-parser/
├── src/
│   ├── app.py                  # Flask REST API エントリポイント
│   ├── collect_configs.py      # FW コンフィグの検出・照合・コピー
│   ├── parse_fw_policy.py      # TTP パース + JSON 保存
│   └── template/
│       └── juniper_srx.ttp     # JunOS SRX 用 TTP テンプレート
├── test/
│   ├── inputs/                 # サンプルコンフィグ (Juniper SRX inherited config)
│   └── expects/                # TTP パース結果の期待値 JSON
├── ttp_input/                  # 実行時: configs dir からコピーした FW コンフィグ
├── ttp_output/                 # 実行時: TTP パース結果の JSON 出力
├── docs/
│   ├── requirements.md
│   ├── design-notes.md
│   └── reviews/
└── CLAUDE.md
```

## 環境変数

| 変数名 | デフォルト値 | 説明 |
|---|---|---|
| `MDDO_CONFIGS_DIR` | `./configs` | 全ノードのコンフィグが混在するディレクトリ |
| `MDDO_FIREWALL_POLICY_PARSER_DIR` | `.` | 作業ディレクトリの基底パス |
| `MDDO_FIREWALL_POLICY_PARSER_CONFIGS_DIR` | `${MDDO_FIREWALL_POLICY_PARSER_DIR}/ttp_input` | FW コンフィグのコピー先 |
| `MDDO_FIREWALL_POLICY_PARSER_OUTPUTS_DIR` | `${MDDO_FIREWALL_POLICY_PARSER_DIR}/ttp_output` | TTP パース結果の保存先 |

`MDDO_FIREWALL_POLICY_PARSER_CONFIGS_DIR` / `MDDO_FIREWALL_POLICY_PARSER_OUTPUTS_DIR` を
明示的に設定した場合はそちらが優先される。未設定の場合は `MDDO_FIREWALL_POLICY_PARSER_DIR`
からの相対パスが使われる。

> **注意**: `MDDO_FIREWALL_POLICY_PARSER_DIR` に書き込み不可のパスが設定されていると
> `PermissionError` が発生する。他の `ool-mddo` サービスと同じ環境で動かす場合は
> 各変数を明示的に指定することを推奨する。

## API

### `POST /fw_policy/<network>/<snapshot>/parsed_result`

指定された network / snapshot のコンフィグを探してパースする。

**Request body**

```json
{
  "node_pairs": [
    { "primary": "<node-name>", "secondary": "<node-name>" }
  ]
}
```

`node_pairs` は SRX cluster のペア情報。コンフィグファイルからは判断できないため
呼び出し元が明示的に指定する。

**処理フロー**

1. `ttp_input/<network>/<snapshot>/` と `ttp_output/<network>/<snapshot>/` を初期化（全削除）
2. `MDDO_CONFIGS_DIR/<network>/<snapshot>/configs/` を再帰的に走査し FW コンフィグを検出
3. `node_pairs` と照合（不一致は error / warning ログに出力）
4. 一致したファイルを `ttp_input/` にコピーし TTP でパース
5. パース結果を `ttp_output/<network>/<snapshot>/<node>.json` に保存

**Response**

```json
{ "parsed": ["site-a-fw-1", "site-a-fw-2"] }
```

**FW コンフィグの識別方法**

以下のコメントを含むファイルを SRX inherited config として判定する:

```
## '<nodename>' was inherited from group 'node0'
## '<nodename>' was inherited from group 'node1'
```

**node_pairs 照合ルール**

| 状況 | ログ |
|---|---|
| node_pairs に指定されているがコンフィグが見つからない | `ERROR` |
| コンフィグは存在するが node_pairs に未指定 | `WARNING` |
| 両方に存在する | 処理対象 |

## セットアップ

```bash
pip install -r requirements_prod.txt
# 開発時
pip install -r requirements_dev.txt
```

## 使い方

### サーバー起動

```bash
MDDO_CONFIGS_DIR=<configs-dir> \
MDDO_FIREWALL_POLICY_PARSER_DIR=. \
python3 src/app.py
```

デフォルトで `http://0.0.0.0:5000` で起動する。

### リクエスト例

```bash
curl -s -X POST \
  http://localhost:5000/fw_policy/<network>/<snapshot>/parsed_result \
  -H 'Content-Type: application/json' \
  -d '{"node_pairs": [{"primary": "site-a-fw-1", "secondary": "site-a-fw-2"}]}' \
  | python3 -m json.tool
```

出力 JSON の確認:

```bash
cat ttp_output/<network>/<snapshot>/site-a-fw-1.json
```

### ローカルのサンプルデータで動作確認する

```bash
# サンプルコンフィグを configs dir 形式に配置
mkdir -p /tmp/testconfigs/net1/snap1/configs
cp test/inputs/*.inheritance /tmp/testconfigs/net1/snap1/configs/

# サーバー起動
MDDO_CONFIGS_DIR=/tmp/testconfigs \
MDDO_FIREWALL_POLICY_PARSER_DIR=. \
python3 src/app.py

# 別ターミナルでリクエスト
curl -s -X POST \
  http://localhost:5000/fw_policy/net1/snap1/parsed_result \
  -H 'Content-Type: application/json' \
  -d '{"node_pairs": [{"primary": "site-a-fw-1", "secondary": "site-a-fw-2"}]}' \
  | python3 -m json.tool
```

### テスト実行

```bash
python3 -m pytest test/ -v
```
