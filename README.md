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
├── .github/
│   └── workflows/
│       ├── docker-build.yml    # push/tag でイメージビルド & GHCR プッシュ
│       └── docker-cleanup.yml  # 古いイメージの定期削除
├── Dockerfile
└── CLAUDE.md
```

## 環境変数

| 変数名 | デフォルト値 | 説明 |
|---|---|---|
| `MDDO_CONFIGS_DIR` | `./configs` | 全ノードのコンフィグが混在するディレクトリ |
| `MDDO_FIREWALL_POLICY_PARSER_DIR` | `.` | 作業ディレクトリの基底パス |
| `MDDO_FIREWALL_POLICY_PARSER_CONFIGS_DIR` | `${MDDO_FIREWALL_POLICY_PARSER_DIR}/ttp_input` | FW コンフィグのコピー先 |
| `MDDO_FIREWALL_POLICY_PARSER_OUTPUTS_DIR` | `${MDDO_FIREWALL_POLICY_PARSER_DIR}/ttp_output` | TTP パース結果の保存先 |
| `MODEL_CONDUCTOR_HOST` | `model-conductor:9292` | model-conductor の接続先 (`host:port` 形式) |

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
  "cluster_firewall_pairs": [
    {
      "primary": {
        "name": "<node-name>",
        "atypical_interfaces": [
          { "name": "<intf>", "role": "<fabric|control>", "fabric_options": { "member_interfaces": ["<intf>"] } }
        ]
      },
      "secondary": {
        "name": "<node-name>",
        "atypical_interfaces": [
          { "name": "<intf>", "role": "<fabric|control>", "fabric_options": { "member_interfaces": ["<intf>"] } }
        ]
      }
    }
  ]
}
```

`cluster_firewall_pairs` は SRX cluster のペア情報。コンフィグファイルからは判断できないため
呼び出し元が明示的に指定する。`atypical_interfaces` には fabric/control などクラスタ固有の
インタフェース情報を含める。

**処理フロー**

1. `ttp_input/<network>/<snapshot>/` と `ttp_output/<network>/<snapshot>/` を初期化（全削除）
2. `MDDO_CONFIGS_DIR/<network>/<snapshot>/configs/` を再帰的に走査し FW コンフィグを検出
3. `cluster_firewall_pairs` と照合（不一致は error / warning ログに出力）
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

**cluster_firewall_pairs 照合ルール**

| 状況 | ログ |
|---|---|
| cluster_firewall_pairs に指定されているがコンフィグが見つからない | `ERROR` |
| コンフィグは存在するが cluster_firewall_pairs に未指定 | `WARNING` |
| 両方に存在する | 処理対象 |

### `POST /fw_policy/<network>/<snapshot>/topology`

`parsed_result` で保存された TTP パース結果を集約し、model-conductor に転送する。

**前提**

`parsed_result` が実行済みで `ttp_output/<network>/<snapshot>/` にデータが存在すること。

**処理フロー**

1. `ttp_output/<network>/<snapshot>/` の全 `*.json` を読み込む
2. 以下の形式に集約する:
   ```json
   {
     "node": [
       {
         "node-id": "site-a-fw-1",
         "mddo-topology:l3-node-attributes": {
           "firewall": { "node": "...", "policies": [...], "zones": [...], ... }
         }
       }
     ]
   }
   ```
3. `http://$MODEL_CONDUCTOR_HOST/conduct/<network>/<snapshot>/topology/layer3/policies` に POST する
4. model-conductor のレスポンスをそのままクライアントに返す

**Response**

- `ttp_output` にファイルが存在しない場合: `404`
- それ以外: model-conductor のステータスコードとレスポンス body をそのまま返す

**リクエスト例**

```bash
curl -s -X POST \
  http://localhost:5000/fw_policy/<network>/<snapshot>/topology \
  | python3 -m json.tool
```

---

## セットアップ

### ローカル実行

```bash
pip install -r requirements_prod.txt
# 開発時
pip install -r requirements_dev.txt
```

### Docker イメージを使う

GitHub Actions により、push/タグごとに自動ビルドされたイメージが
[GHCR (GitHub Container Registry)](https://github.com/ool-mddo/firewall-policy-parser/pkgs/container/firewall-policy-parser) に公開される。

```bash
docker pull ghcr.io/ool-mddo/firewall-policy-parser:latest
```

## 使い方

### サーバー起動 (ローカル)

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
  -d '{"cluster_firewall_pairs": [{"primary": {"name": "site-a-fw-1"}, "secondary": {"name": "site-a-fw-2"}}]}' \
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
  -d '{"cluster_firewall_pairs": [{"primary": {"name": "site-a-fw-1"}, "secondary": {"name": "site-a-fw-2"}}]}' \
  | python3 -m json.tool
```

### コンテナで起動する

configs ディレクトリをボリュームマウントして起動する:

```bash
docker run -p 5000:5000 \
  -e MDDO_CONFIGS_DIR=/configs \
  -v /path/to/configs:/configs:ro \
  ghcr.io/ool-mddo/firewall-policy-parser:latest
```

出力 JSON を取り出したい場合は `ttp_output/` もマウントする:

```bash
docker run -p 5000:5000 \
  -e MDDO_CONFIGS_DIR=/configs \
  -e MDDO_FIREWALL_POLICY_PARSER_OUTPUTS_DIR=/output \
  -v /path/to/configs:/configs:ro \
  -v /path/to/output:/output \
  ghcr.io/ool-mddo/firewall-policy-parser:latest
```

### コンテナでサンプルデータを動作確認する

```bash
# サンプルコンフィグを configs dir 形式に配置
mkdir -p /tmp/testconfigs/net1/snap1/configs
cp test/inputs/*.inheritance /tmp/testconfigs/net1/snap1/configs/

# コンテナ起動
docker run -p 5000:5000 \
  -e MDDO_CONFIGS_DIR=/configs \
  -v /tmp/testconfigs:/configs:ro \
  ghcr.io/ool-mddo/firewall-policy-parser:latest

# 別ターミナルでリクエスト
curl -s -X POST \
  http://localhost:5000/fw_policy/net1/snap1/parsed_result \
  -H 'Content-Type: application/json' \
  -d '{"cluster_firewall_pairs": [{"primary": {"name": "site-a-fw-1"}, "secondary": {"name": "site-a-fw-2"}}]}' \
  | python3 -m json.tool
```

### テスト実行

```bash
python3 -m pytest test/ -v
```

## CI/CD

GitHub Actions により以下が自動化されている。

| ワークフロー | ファイル | トリガー |
|---|---|---|
| イメージビルド & プッシュ | `.github/workflows/docker-build.yml` | 全ブランチ push / タグ push |
| 古いイメージ削除 | `.github/workflows/docker-cleanup.yml` | 毎週日曜0時 / ビルド完了後 / 手動 |

ビルドワークフローはテストが成功した場合のみイメージをプッシュする。
イメージは最新 10 件を保持し、semver タグ (`v1.0.0` 形式) は自動削除の対象外となる。

**タグ付けルール**

| 状況 | 付与されるタグ |
|---|---|
| 全 push | `sha-<7桁ハッシュ>` |
| main への push | + `latest` |
| ブランチ push | + `<branch-name>` |
| タグ push (`v1.0.0`) | + `v1.0.0`, `1.0` |
