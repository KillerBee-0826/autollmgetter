from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parent


class AnalysisPromptTests(unittest.TestCase):
    def _read_prompt(self, name):
        return (REPO_ROOT / "config" / name).read_text(encoding="utf-8")

    def test_daily_prompt_uses_structured_article_extraction_table(self):
        prompt = self._read_prompt("news_analysis_prompt.txt")

        self.assertIn("### 2. 記事別構造化抽出", prompt)
        self.assertIn(
            "| 媒体名 | 技術カテゴリ | 記事タイトル | 主要論点 | 背景・文脈 | "
            "技術・製品・企業 | 何が新しいか | 週次分析で使う観測ポイント | URL |",
            prompt
        )
        self.assertNotIn("### 2. 記事一覧・要約", prompt)
        self.assertNotIn("短い要約", prompt)

    def test_daily_prompt_keeps_fixed_category_count_rules(self):
        prompt = self._read_prompt("news_analysis_prompt.txt")

        self.assertIn("次の5カテゴリだけを使い", prompt)
        for category in ["生成AI", "セキュリティ", "クラウド", "開発", "その他"]:
            self.assertIn(category, prompt)
        self.assertIn("| 技術カテゴリ | 件数 | 代表的な記事タイトル |", prompt)
        self.assertIn("件数は `3` のような数値だけ", prompt)

    def test_weekly_prompt_references_daily_structured_columns(self):
        prompt = self._read_prompt("weekly_news_analysis_prompt.txt")

        self.assertIn("記事別構造化抽出", prompt)
        for column in [
            "主要論点",
            "背景・文脈",
            "技術・製品・企業",
            "何が新しいか",
            "週次分析で使う観測ポイント",
        ]:
            self.assertIn(column, prompt)
        self.assertIn("複数日の観測ポイントを横断してテーマ化", prompt)
        self.assertIn("日次レポートに書かれていない事実は補完して断定しない", prompt)

    def test_quarterly_prompt_has_required_placeholders(self):
        prompt = self._read_prompt("quarterly_news_analysis_prompt.txt")

        for placeholder in [
            "{quarter_label}",
            "{period_start}",
            "{period_end}",
            "{monthly_analyses}",
        ]:
            self.assertIn(placeholder, prompt)
        self.assertIn("四半期総括", prompt)
        self.assertIn("月次レポートだけを根拠", prompt)


if __name__ == "__main__":
    unittest.main()
