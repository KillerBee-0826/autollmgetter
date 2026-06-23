#!/usr/bin/env python3
"""
ニュースサイトスクレイピングモジュール
複数のITニュースサイトから記事を取得し、LLM用にフォーマットします。
"""

import re
import time
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from urllib.parse import urljoin
from concurrent.futures import ThreadPoolExecutor, as_completed
from email.utils import parsedate_to_datetime

import pytz
import requests
import feedparser
import chardet
import trafilatura
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


class NewsScraper:
    """ニュースサイトからの記事取得クラス"""

    def __init__(self, config: dict, logger: logging.Logger):
        """
        初期化

        Args:
            config: 設定辞書
            logger: ロガーインスタンス
        """
        self.config = config
        self.logger = logger
        self.session = self._create_session()
        self.target_date = self._get_target_date()

        self.logger.info(f"スクレイピング対象日: {self.target_date.strftime('%Y-%m-%d')}")

    def _create_session(self) -> requests.Session:
        """リトライ設定付きセッション作成"""
        session = requests.Session()
        session.headers.update({
            'User-Agent': self.config['news_scraping']['user_agent']
        })

        # リトライ設定
        retry = Retry(
            total=3,
            backoff_factor=0.3,
            status_forcelist=[500, 502, 503, 504]
        )
        adapter = HTTPAdapter(max_retries=retry)
        session.mount('http://', adapter)
        session.mount('https://', adapter)

        return session

    def _get_target_date(self) -> datetime:
        """スクレイピング対象日（前日）を取得"""
        tz = pytz.timezone(self.config['news_scraping']['timezone'])
        now = datetime.now(tz)
        yesterday = now - timedelta(days=1)
        return yesterday.replace(hour=0, minute=0, second=0, microsecond=0)

    def scrape_all_sites(self) -> Dict[str, List[dict]]:
        """
        全サイトから記事を並列取得

        Returns:
            サイト名をキーとした記事リストの辞書
        """
        sites = self.config['news_scraping']['sites']
        workers = self.config['news_scraping']['parallel_workers']
        timeout = self.config['news_scraping']['timeout_per_site']

        articles_by_site = {}

        self.logger.info(f"スクレイピング開始: {len(sites)}サイトを{workers}並列で処理")

        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_to_site = {
                executor.submit(self._scrape_site_with_timeout, site, timeout): site
                for site in sites
            }

            for future in as_completed(future_to_site):
                site = future_to_site[future]
                try:
                    articles = future.result(timeout=timeout + 5)
                    articles_by_site[site['name']] = articles
                    self.logger.info(f"{site['name']}: {len(articles)}記事取得")
                except Exception as e:
                    self.logger.error(f"{site['name']}: エラー - {str(e)}")
                    articles_by_site[site['name']] = []

        total_articles = sum(len(articles) for articles in articles_by_site.values())
        self.logger.info(f"スクレイピング完了: 合計{total_articles}記事取得")

        return articles_by_site

    def _scrape_site_with_timeout(self, site_config: dict, timeout: int) -> List[dict]:
        """
        タイムアウト付きでサイトをスクレイピング

        Args:
            site_config: サイト設定
            timeout: タイムアウト秒数

        Returns:
            記事リスト
        """
        try:
            return self.scrape_site(site_config)
        except Exception as e:
            self.logger.warning(f"{site_config['name']}: スクレイピング失敗 - {str(e)}")
            return []

    def scrape_site(self, site_config: dict) -> List[dict]:
        """
        単一サイトからの記事取得（RSS優先）

        Args:
            site_config: サイト設定

        Returns:
            記事リスト
        """
        site_name = site_config['name']

        # RSS取得を試行
        if site_config.get('rss_url'):
            try:
                articles = self._fetch_from_rss(site_config['rss_url'], site_name)
                if articles:
                    self.logger.debug(f"{site_name}: RSSから{len(articles)}記事取得")
                    return articles
            except Exception as e:
                self.logger.warning(f"{site_name}: RSS取得失敗 - {str(e)}")

        # HTMLフォールバック
        self.logger.info(f"{site_name}: HTMLフォールバックを試行")
        return self._fetch_from_html(site_config)

    def _fetch_from_rss(self, rss_url: str, site_name: str) -> List[dict]:
        """
        RSSフィードから記事を取得

        Args:
            rss_url: RSSフィードURL
            site_name: サイト名

        Returns:
            記事リスト
        """
        try:
            response = self._fetch_with_retry(rss_url)
            if not response:
                return []

            feed = feedparser.parse(response.content)

            if not feed.entries:
                self.logger.warning(f"{site_name}: RSSエントリが空です")
                return []

            articles = []
            max_articles = self.config['news_scraping']['max_articles_per_site']

            for entry in feed.entries[:max_articles * 2]:  # フィルタリング前に多めに取得
                try:
                    # 日付解析
                    article_date = None
                    if hasattr(entry, 'published'):
                        article_date = self._parse_rss_date(entry.published)
                    elif hasattr(entry, 'updated'):
                        article_date = self._parse_rss_date(entry.updated)

                    # 前日の記事のみフィルタリング
                    if not self._is_yesterday_article(article_date):
                        continue

                    # タイトル、URL、概要を取得
                    title = entry.title if hasattr(entry, 'title') else "タイトルなし"
                    url = entry.link if hasattr(entry, 'link') else ""

                    # 概要（description/summary）を取得
                    description = ""
                    if hasattr(entry, 'summary'):
                        description = entry.summary
                    elif hasattr(entry, 'description'):
                        description = entry.description

                    articles.append({
                        'title': title,
                        'url': url,
                        'description': description,
                        'date': article_date,
                        'source': site_name
                    })

                    if len(articles) >= max_articles:
                        break

                except Exception as e:
                    self.logger.debug(f"{site_name}: エントリ解析エラー - {str(e)}")
                    continue

            return articles

        except Exception as e:
            self.logger.error(f"{site_name}: RSS取得エラー - {str(e)}")
            return []

    def _parse_rss_date(self, date_str: str) -> Optional[datetime]:
        """
        RSS日付の柔軟なパース

        Args:
            date_str: 日付文字列

        Returns:
            datetime オブジェクト、またはNone
        """
        if not date_str:
            return None

        # RFC 2822形式（RSS標準）
        try:
            return parsedate_to_datetime(date_str)
        except:
            pass

        # ISO 8601形式（Atom標準）
        try:
            return datetime.fromisoformat(date_str.replace('Z', '+00:00'))
        except:
            pass

        # 日本語形式（例: "2026年4月21日"）
        try:
            match = re.match(r'(\d{4})年(\d{1,2})月(\d{1,2})日', date_str)
            if match:
                year, month, day = match.groups()
                tz = pytz.timezone(self.config['news_scraping']['timezone'])
                return tz.localize(datetime(int(year), int(month), int(day)))
        except:
            pass

        self.logger.debug(f"日付パース失敗: {date_str}")
        return None

    def _fetch_from_html(self, site_config: dict) -> List[dict]:
        """
        HTMLから記事を取得（フォールバック）

        Args:
            site_config: サイト設定

        Returns:
            記事リスト
        """
        site_name = site_config['name']

        try:
            response = self._fetch_with_retry(site_config['url'])
            if not response:
                return []

            soup = BeautifulSoup(response.content, 'lxml')
            articles = []
            max_articles = self.config['news_scraping']['max_articles_per_site']

            # 汎用セレクタで記事要素を検索
            selectors = ['article', '.article', '[data-article]', '.news-item']
            article_elements = []

            for selector in selectors:
                article_elements = soup.select(selector)
                if article_elements:
                    break

            if not article_elements:
                self.logger.warning(f"{site_name}: HTML解析で記事要素が見つかりません")
                return []

            for elem in article_elements[:max_articles]:
                try:
                    # タイトルとリンクを取得
                    title_elem = elem.find(['h2', 'h3', 'h1', 'a'])
                    if not title_elem:
                        continue

                    title = title_elem.get_text(strip=True)
                    link_elem = elem.find('a')
                    url = urljoin(site_config['url'], link_elem['href']) if link_elem else ""

                    # 概要を取得（p, .description, .summary など）
                    description = ""
                    desc_elem = elem.find(['p', '.description', '.summary', '.excerpt'])
                    if desc_elem:
                        description = desc_elem.get_text(strip=True)

                    # 日付は取得困難なため、前日として扱う
                    articles.append({
                        'title': title,
                        'url': url,
                        'description': description,
                        'date': self.target_date,
                        'source': site_name
                    })

                except Exception as e:
                    self.logger.debug(f"{site_name}: HTML要素解析エラー - {str(e)}")
                    continue

            return articles

        except Exception as e:
            self.logger.error(f"{site_name}: HTML取得エラー - {str(e)}")
            return []

    def _is_yesterday_article(self, article_date: Optional[datetime]) -> bool:
        """
        前日の記事か判定（タイムゾーン考慮）

        Args:
            article_date: 記事の日付

        Returns:
            前日の記事であればTrue
        """
        if not article_date:
            return False

        # タイムゾーンを揃える
        tz = pytz.timezone(self.config['news_scraping']['timezone'])
        if article_date.tzinfo is None:
            article_date = tz.localize(article_date)
        else:
            article_date = article_date.astimezone(tz)

        article_day = article_date.replace(hour=0, minute=0, second=0, microsecond=0)
        target_day = self.target_date.replace(hour=0, minute=0, second=0, microsecond=0)

        return article_day == target_day

    def _fetch_with_retry(self, url: str) -> Optional[requests.Response]:
        """
        指数バックオフリトライでURLを取得

        Args:
            url: 取得するURL

        Returns:
            Responseオブジェクト、またはNone
        """
        max_retries = self.config['max_retries']
        retry_delay = self.config['retry_delay']

        for attempt in range(max_retries):
            try:
                response = self.session.get(url, timeout=(10, 30))
                response.raise_for_status()
                return response
            except requests.RequestException as e:
                self.logger.debug(f"試行{attempt+1}/{max_retries}失敗: {url} - {e}")
                if attempt < max_retries - 1:
                    wait_time = retry_delay * (2 ** attempt)
                    time.sleep(wait_time)

        return None

    def enrich_articles_with_content(self, articles_by_site: Dict[str, List[dict]]) -> Dict[str, List[dict]]:
        """
        記事リストに本文を一括追加（並列処理）

        Args:
            articles_by_site: サイト名をキーとした記事リストの辞書

        Returns:
            本文が追加された記事リストの辞書
        """
        content_config = self.config['news_scraping'].get('content_fetching', {})
        if not content_config.get('enabled', False):
            self.logger.info("記事本文取得は無効化されています")
            return articles_by_site

        workers = content_config.get('parallel_content_workers', 5)
        timeout = content_config.get('timeout_per_article', 10)

        # 全記事をフラットリストに変換
        all_articles = []
        for site_name, articles in articles_by_site.items():
            for article in articles:
                article['site_name'] = site_name
                all_articles.append(article)

        self.logger.info(f"記事本文取得開始: {len(all_articles)}件を{workers}並列で処理")

        # 統計情報
        stats = {'success': 0, 'failed': 0, 'total_chars': 0, 'max_chars': 0, 'min_chars': float('inf')}

        # 並列処理
        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_to_article = {
                executor.submit(self._fetch_article_content, article['url'], article['site_name']): article
                for article in all_articles
            }

            for future in as_completed(future_to_article):
                article = future_to_article[future]
                try:
                    content = future.result(timeout=timeout + 2)
                    if content:
                        article['content'] = content
                        stats['success'] += 1
                        stats['total_chars'] += len(content)
                        stats['max_chars'] = max(stats['max_chars'], len(content))
                        stats['min_chars'] = min(stats['min_chars'], len(content))
                    else:
                        article['content'] = None
                        stats['failed'] += 1
                except Exception as e:
                    self.logger.error(f"記事本文取得失敗: {article['url']} - {e}")
                    article['content'] = None
                    stats['failed'] += 1

        # 統計情報をログ出力
        total = stats['success'] + stats['failed']
        success_rate = (stats['success'] / total * 100) if total > 0 else 0
        avg_chars = (stats['total_chars'] / stats['success']) if stats['success'] > 0 else 0

        self.logger.info(f"記事本文取得完了:")
        self.logger.info(f"  総数: {total}件")
        self.logger.info(f"  成功: {stats['success']}件 ({success_rate:.1f}%)")
        self.logger.info(f"  失敗: {stats['failed']}件")
        if stats['success'] > 0:
            self.logger.info(f"  平均文字数: {avg_chars:.0f}文字")
            self.logger.info(f"  最大文字数: {stats['max_chars']}文字")
            self.logger.info(f"  最小文字数: {stats['min_chars']}文字")

        return articles_by_site

    def _fetch_article_content(self, url: str, site_name: str) -> Optional[str]:
        """
        単一記事の本文取得（3段階フォールバック）

        Args:
            url: 記事URL
            site_name: サイト名

        Returns:
            記事本文、または None
        """
        try:
            # HTTP取得
            response = self._fetch_with_retry(url)
            if not response:
                self.logger.debug(f"HTTP取得失敗: {url}")
                return None

            # エンコーディング検出とデコード
            html = self._decode_response(response, site_name)

            # Phase 1: trafilatura 汎用抽出
            content = self._extract_with_trafilatura(html)
            if content and self._validate_content(content):
                self.logger.debug(f"trafilatura成功: {url}")
                return content

            # Phase 2: サイト特化セレクタ
            content = self._extract_with_site_specific(html, site_name)
            if content and self._validate_content(content):
                self.logger.debug(f"サイト特化成功: {url}")
                return content

            # Phase 3: BeautifulSoup 汎用フォールバック
            soup = BeautifulSoup(html, 'lxml')
            content = self._fallback_extract(soup)
            if content and self._validate_content(content):
                self.logger.debug(f"汎用フォールバック成功: {url}")
                return content

            self.logger.debug(f"全フォールバック失敗: {url}")
            return None

        except Exception as e:
            self.logger.error(f"記事本文取得エラー: {url} - {e}")
            return None

    def _decode_response(self, response: requests.Response, site_name: str) -> str:
        """
        エンコーディング検出とデコード（ITmedia対策）

        Args:
            response: HTTPレスポンス
            site_name: サイト名

        Returns:
            デコードされたHTML文字列
        """
        # ITmediaの場合のみchardetを使用
        site_config = None
        for site in self.config['news_scraping']['sites']:
            if site['name'] == site_name:
                site_config = site
                break

        if site_config and site_config.get('encoding_fix') == 'chardet':
            try:
                # まずHTTPヘッダーのエンコーディングを確認
                content_type = response.headers.get('Content-Type', '')
                declared_encoding = None
                if 'charset=' in content_type:
                    declared_encoding = content_type.split('charset=')[1].split(';')[0].strip()

                # chardetで自動検出
                detected = chardet.detect(response.content)
                detected_encoding = detected.get('encoding', 'utf-8')
                confidence = detected.get('confidence', 0)

                self.logger.debug(f"{site_name}: 宣言エンコーディング={declared_encoding}, "
                                f"検出エンコーディング={detected_encoding} (信頼度={confidence:.2f})")

                # chardetの信頼度が高い場合は、それを優先的に使用
                if detected_encoding and confidence > 0.8:
                    try:
                        html = response.content.decode(detected_encoding)
                        self.logger.debug(f"{site_name}: エンコーディング={detected_encoding}で成功（chardet信頼度{confidence:.2f}）")
                        return html
                    except (UnicodeDecodeError, AttributeError, LookupError) as e:
                        self.logger.debug(f"{site_name}: {detected_encoding}デコード失敗 - {e}")

                # 試行するエンコーディングのリスト（優先順位順）
                encodings_to_try = []
                if declared_encoding:
                    encodings_to_try.append(declared_encoding.lower())
                if detected_encoding:
                    encodings_to_try.append(detected_encoding.lower())

                # 日本語サイトの一般的なエンコーディングを追加
                for enc in ['utf-8', 'cp932', 'shift_jis', 'euc-jp', 'iso-2022-jp']:
                    if enc not in encodings_to_try:
                        encodings_to_try.append(enc)

                # 複数エンコーディングを試行
                for enc in encodings_to_try:
                    if not enc:
                        continue
                    try:
                        html = response.content.decode(enc)
                        # 簡易的な文字化けチェック
                        if '�' not in html[:1000]:  # 最初の1000文字で判定
                            self.logger.debug(f"{site_name}: エンコーディング={enc}で成功")
                            return html
                    except (UnicodeDecodeError, AttributeError, LookupError):
                        continue

                # 全失敗時はエラー無視でデコード
                self.logger.warning(f"{site_name}: エンコーディング検出失敗、UTF-8でデコード")
                return response.content.decode('utf-8', errors='replace')

            except Exception as e:
                self.logger.warning(f"{site_name}: chardet処理エラー - {e}")
                # エラー時もchardetの結果を信頼してデコードを試みる
                try:
                    return response.content.decode('utf-8', errors='replace')
                except:
                    return response.text
        else:
            # ITmedia以外は通常のresponse.text（requestsの自動判定を信頼）
            # ただし、明示的にUTF-8でエラー無視デコードも可能
            return response.text

    def _extract_with_trafilatura(self, html: str) -> Optional[str]:
        """
        trafilatura ライブラリで記事本文を抽出

        Args:
            html: HTML文字列

        Returns:
            記事本文、または None
        """
        try:
            content = trafilatura.extract(html, include_comments=False, include_tables=True)
            if content and len(content) >= 200:
                return content
        except Exception as e:
            self.logger.debug(f"trafilatura抽出失敗: {e}")

        return None

    def _extract_with_site_specific(self, html: str, site_name: str) -> Optional[str]:
        """
        サイト特化CSSセレクタで抽出

        Args:
            html: HTML文字列
            site_name: サイト名

        Returns:
            記事本文、または None
        """
        try:
            # サイト設定を取得
            site_config = None
            for site in self.config['news_scraping']['sites']:
                if site['name'] == site_name:
                    site_config = site
                    break

            if not site_config or 'content_selectors' not in site_config:
                return None

            soup = BeautifulSoup(html, 'lxml')
            selectors_config = site_config['content_selectors']

            # 記事要素を検索
            article_selectors = selectors_config.get('article', [])
            for selector in article_selectors:
                elem = soup.select_one(selector)
                if elem:
                    # 除外要素を削除
                    remove_selectors = selectors_config.get('remove', [])
                    for remove_sel in remove_selectors:
                        for tag in elem.select(remove_sel):
                            tag.decompose()

                    # テキスト抽出
                    text = elem.get_text(strip=True, separator='\n')
                    if len(text) >= 200:
                        return text

        except Exception as e:
            self.logger.debug(f"サイト特化抽出失敗: {e}")

        return None

    def _fallback_extract(self, soup: BeautifulSoup) -> Optional[str]:
        """
        BeautifulSoupで汎用的に本文抽出

        Args:
            soup: BeautifulSoupオブジェクト

        Returns:
            記事本文、または None
        """
        try:
            # 汎用セレクタで記事本文を推測
            selectors = ['article', '.article', 'main', '.main', '.content', '#content']

            for selector in selectors:
                elem = soup.select_one(selector)
                if elem:
                    # 不要要素を削除
                    for tag in elem.find_all(['script', 'style', 'nav', 'header', 'footer', 'aside']):
                        tag.decompose()

                    # テキスト抽出
                    text = elem.get_text(strip=True, separator='\n')
                    if len(text) >= 200:
                        return text

        except Exception as e:
            self.logger.debug(f"汎用フォールバック失敗: {e}")

        return None

    def _validate_content(self, content: str) -> bool:
        """
        記事本文の品質検証

        Args:
            content: 記事本文

        Returns:
            品質基準を満たすかどうか
        """
        if not content:
            return False

        # 最小文字数チェック
        content_config = self.config['news_scraping'].get('content_fetching', {})
        min_length = content_config.get('min_content_length', 200)
        max_length = content_config.get('max_content_length', 50000)

        if len(content) < min_length:
            return False

        if len(content) > max_length:
            # 長すぎる場合は切り詰める
            return True

        # ボイラープレート検出（広告キーワード）
        spam_keywords = ['広告', 'PR', 'スポンサー', '提供:', '【PR】', 'Advertisement']
        spam_count = sum(1 for kw in spam_keywords if kw in content)
        if spam_count >= 5:
            self.logger.debug("ボイラープレート検出: 広告キーワードが多い")
            return False

        # 文字化けチェック
        garbled_count = content.count('〓') + content.count('�')
        if garbled_count > len(content) * 0.05:
            self.logger.debug("文字化け検出: 不正文字が5%以上")
            return False

        return True

    def format_articles_for_llm(self, articles_by_site: Dict[str, List[dict]]) -> str:
        """
        LLM用に記事をフォーマット

        Args:
            articles_by_site: サイト名をキーとした記事リストの辞書

        Returns:
            フォーマットされた記事テキスト
        """
        max_per_site = self.config['news_scraping']['max_articles_per_site']

        formatted = f"# {self.target_date.strftime('%Y年%m月%d日')}の技術ニュース\n\n"

        total_articles = 0
        for site_name, articles in articles_by_site.items():
            limited_articles = articles[:max_per_site]
            total_articles += len(limited_articles)

            formatted += f"## {site_name} ({len(limited_articles)}件)\n\n"

            if not limited_articles:
                formatted += "（記事なし）\n\n"
                continue

            for i, article in enumerate(limited_articles, 1):
                formatted += f"{i}. [{article['title']}]({article['url']})\n"
                if article.get('date'):
                    formatted += f"   発行日時: {article['date'].strftime('%Y-%m-%d %H:%M')}\n"
                if article.get('description'):
                    formatted += f"   概要: {article['description']}\n"

                # 記事本文を追加
                if article.get('content'):
                    # 最大5000文字に制限（トークン対策）
                    content = article['content'][:5000]
                    if len(article['content']) > 5000:
                        content += "...(省略)"
                    formatted += f"\n   【本文】\n   {content}\n"
                else:
                    formatted += f"\n   【本文取得失敗】\n"

                formatted += "\n   ---\n\n"

        formatted += f"\n**合計記事数**: {total_articles}件\n"

        self.logger.info(f"記事フォーマット完了: 合計{total_articles}件")

        return formatted
