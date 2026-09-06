# firewall-policy-parser

## 概要
ネットワーク機器のコンフィグから Firewall policy 情報を抽出し、JSON 形式で出力する REST API サービス。

## 対象機器
- Juniper SRX (JunOS 階層型コンフィグ形式)
- SRX cluster の node0/node1 は個別ノードとして扱う

## 技術スタック
- 言語: Python
- パースライブラリ: TTP (Template Text Parser)
- API フレームワーク: Flask
- 出力形式: JSON

## アーキテクチャ
2ステージパイプライン:
1. TTP パース: コンフィグファイル → TTP raw JSON (ttp_output)
2. (将来) policy model 変換: TTP raw JSON → 正規化 policy model JSON

## ディレクトリ構成
```
src/
  app.py                    # Flask REST API エントリポイント
  collect_configs.py        # configs dir → ttp_input コピー処理
  parse_fw_policy.py        # TTP パース + ttp_output 保存処理
  template/
    juniper_srx.ttp         # SRX用 TTPテンプレート
test/
  inputs/                   # サンプルコンフィグ
  expects/                  # TTP出力の期待値
```

## 環境変数
- `MDDO_CONFIGS_DIR`: 全ノードのコンフィグが混在するディレクトリ (default: `./configs`)
- `MDDO_FIREWALL_POLICY_PARSER_DIR`: パーサー作業ディレクトリ基底 (default: `.`)
- `MDDO_FIREWALL_POLICY_PARSER_CONFIGS_DIR`: FWコンフィグコピー先 (default: `${MDDO_FIREWALL_POLICY_PARSER_DIR}/ttp_input`)
- `MDDO_FIREWALL_POLICY_PARSER_OUTPUTS_DIR`: TTPパース結果保存先 (default: `${MDDO_FIREWALL_POLICY_PARSER_DIR}/ttp_output`)

## REST API
```
POST /fw_policy/<network>/<snapshot>/parsed_result
Body: { "node_pairs": [{"primary": "<node>", "secondary": "<node>"}] }
```
- 毎回 `ttp_input/<network>/<snapshot>/` と `ttp_output/<network>/<snapshot>/` を初期化(全削除)してから処理する

## FW コンフィグの識別方法
`MDDO_CONFIGS_DIR/<network>/<snapshot>/configs/` 以下を再帰的に走査し、
JunOS inherited config に含まれる以下のコメントで判定する:
```
## '<nodename>' was inherited from group 'node0'
## '<nodename>' was inherited from group 'node1'
```

## node_pairs との照合ルール
- node_pairs に指定されているがコンフィグが見つからない → `logger.error`
- コンフィグは存在するが node_pairs に未指定 → `logger.warning`
- 両方に存在するノードのみ処理対象とする

## コンテナ
- イメージ: `ghcr.io/ool-mddo/firewall-policy-parser`
- `MDDO_FIREWALL_POLICY_PARSER_DIR=/app` を固定済み (`ttp_input/`・`ttp_output/` は `/app` 以下に生成)
- `MDDO_CONFIGS_DIR` は実行時に `-e` で渡す。configs ディレクトリはボリュームマウントで提供する
- 出力 JSON を外部から取り出す場合は `MDDO_FIREWALL_POLICY_PARSER_OUTPUTS_DIR` を設定してマウント

## CI/CD
- `.github/workflows/docker-build.yml`: 全ブランチ push + `v*` タグ push でテスト → イメージビルド → GHCR プッシュ
- `.github/workflows/docker-cleanup.yml`: 最新10件を保持して古いイメージを削除 (毎週日曜 / ビルド完了後 / 手動)
- semver タグ (`v1.0.0` 形式) は自動削除の対象外

## 参考実装
[bgp-policy-parser](https://github.com/ool-mddo/bgp-policy-parser) (同プロジェクトの BGP ポリシーパーサー)
