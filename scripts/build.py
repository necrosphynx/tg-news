#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import yaml
import feedparser
import json
from datetime import datetime, timedelta
from collections import defaultdict
from jinja2 import Environment, FileSystemLoader
from urllib.parse import urlparse
import re
import html
import sys

# Force UTF-8 for stdout and stderr
if sys.stdout.encoding != 'utf-8':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# Configuration
SITE_DIR = "site"
TEMPLATES_DIR = "templates"

def clean_text(text):
    """Clean and properly encode text from RSS feeds"""
    if not text:
        return "No content available"
    
    # Handle HTML entities
    text = html.unescape(text)
    
    # Remove invalid XML characters
    text = re.sub(r'[^\x09\x0A\x0D\x20-\uD7FF\uE000-\uFFFD\u10000-\u10FFFF]', '', text)
    
    # Replace common problematic Unicode characters
    replacements = {
        '\u2018': "'",  # Left single quote
        '\u2019': "'",  # Right single quote
        '\u201C': '"',  # Left double quote
        '\u201D': '"',  # Right double quote
        '\u2013': '-',  # En dash
        '\u2014': '-',  # Em dash
        '\u2022': '*',  # Bullet
        '\u2026': '...', # Ellipsis
        '\u00A0': ' ',  # Non-breaking space
        '\u00AB': '"',  # Left guillemet
        '\u00BB': '"',  # Right guillemet
        '\u2039': "'",  # Single left angle quote
        '\u203A': "'",  # Single right angle quote
    }
    
    for unicode_char, replacement in replacements.items():
        text = text.replace(unicode_char, replacement)
    
    # Remove any remaining non-printable characters
    text = ''.join(char for char in text if char.isprintable() or char.isspace())
    
    # Ensure it's valid UTF-8
    try:
        text = text.encode('utf-8', errors='ignore').decode('utf-8')
    except:
        text = text.encode('ascii', errors='ignore').decode('ascii')
    
    return text.strip()

def fix_encoding(text):
    """Fix common encoding issues from RSS feeds"""
    if not text:
        return text
    
    # If it's bytes, decode it
    if isinstance(text, bytes):
        for encoding in ['utf-8', 'latin-1', 'windows-1252', 'iso-8859-1']:
            try:
                text = text.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
    
    # Try to fix common mojibake issues
    if isinstance(text, str):
        replacements = {
            'â€˜': "'",
            'â€™': "'",
            'â€œ': '"',
            'â€': '"',
            'â€“': '-',
            'â€”': '-',
            'â€¦': '...',
            'Â': '',
            'Ã©': 'e',
            'Ã¨': 'e',
            'Ãª': 'e',
            'Ã«': 'e',
            'Ã§': 'c',
            'Ã¶': 'o',
            'Ã¼': 'u',
            'Ã¯': 'i',
            'Ã®': 'i',
            'Ã²': 'o',
            'Ã¹': 'u',
        }
        
        for wrong, correct in replacements.items():
            text = text.replace(wrong, correct)
    
    return text

class ArticleRanker:
    """Rank articles based on various metrics"""
    
    def __init__(self):
        self.weights = {
            'recency': 0.30,
            'source_authority': 0.25,
            'engagement': 0.20,
            'content_quality': 0.15,
            'trending': 0.10
        }
        
        self.source_authority = {
            'reuters.com': 0.95,
            'apnews.com': 0.95,
            'bbc.com': 0.90,
            'nytimes.com': 0.90,
            'washingtonpost.com': 0.85,
            'cnn.com': 0.80,
            'theguardian.com': 0.85,
            'bloomberg.com': 0.90,
            'wsj.com': 0.90,
            'economist.com': 0.85,
        }
        
        self.trending_keywords = [
            'ai', 'artificial intelligence', 'climate', 'crypto', 'blockchain',
            'pandemic', 'election', 'war', 'inflation', 'recession', 'space',
            'elon musk', 'trump', 'biden', 'ukraine', 'israel', 'china',
            'technology', 'innovation', 'sustainability', 'quantum computing'
        ]
    
    def calculate_recency_score(self, pub_date):
        try:
            if isinstance(pub_date, str):
                for fmt in ['%a, %d %b %Y %H:%M:%S %Z', '%Y-%m-%dT%H:%M:%SZ', '%Y-%m-%d %H:%M:%S']:
                    try:
                        pub_datetime = datetime.strptime(pub_date, fmt)
                        break
                    except ValueError:
                        continue
                else:
                    return 0.5
            else:
                pub_datetime = pub_date
            
            now = datetime.now()
            hours_diff = (now - pub_datetime).total_seconds() / 3600
            
            if hours_diff < 1:
                return 1.0
            elif hours_diff < 24:
                return 0.9 * (0.9 ** (hours_diff / 24))
            elif hours_diff < 72:
                return 0.7 * (0.8 ** ((hours_diff - 24) / 24))
            else:
                return max(0.1, 0.5 * (0.7 ** ((hours_diff - 72) / 24)))
                
        except Exception:
            return 0.5
    
    def calculate_source_authority_score(self, source_domain):
        domain = source_domain.lower().replace('www.', '')
        return self.source_authority.get(domain, 0.5)
    
    def calculate_engagement_score(self, entry):
        score = 0.5
        if hasattr(entry, 'comments'):
            try:
                comments = int(entry.comments)
                if comments > 100:
                    score += 0.3
                elif comments > 50:
                    score += 0.2
                elif comments > 10:
                    score += 0.1
            except:
                pass
        if hasattr(entry, 'media_content') and entry.media_content:
            score += 0.1
        if hasattr(entry, 'links') and len(entry.links) > 3:
            score += 0.05
        return min(1.0, score)
    
    def calculate_content_quality_score(self, entry):
        score = 0.5
        title = entry.get('title', '')
        summary = entry.get('summary', '')
        title_length = len(title)
        summary_length = len(summary)
        if 40 < title_length < 100:
            score += 0.1
        if 150 < summary_length < 500:
            score += 0.1
        if summary:
            try:
                from textstat import flesch_reading_ease
                try:
                    readability = flesch_reading_ease(summary)
                    if readability > 60:
                        score += 0.1
                    elif readability > 30:
                        score += 0.05
                except:
                    pass
            except:
                pass
        clickbait_words = ['shocked', 'amazing', 'incredible', "you won't believe", 
                          'must see', 'unbelievable', 'mind-blowing', 'breaking']
        if any(word in title.lower() for word in clickbait_words):
            score -= 0.1
        return min(1.0, max(0.0, score))
    
    def calculate_trending_score(self, entry):
        score = 0.0
        content = (entry.get('title', '') + ' ' + entry.get('summary', '')).lower()
        for keyword in self.trending_keywords:
            if keyword.lower() in content:
                score += 0.15
        current_year = datetime.now().year
        if str(current_year) in content:
            score += 0.05
        return min(1.0, score)
    
    def rank_articles(self, articles):
        ranked_articles = []
        for article in articles:
            recency = self.calculate_recency_score(article.get('published'))
            source_auth = self.calculate_source_authority_score(article.get('source', ''))
            engagement = self.calculate_engagement_score(article)
            quality = self.calculate_content_quality_score(article)
            trending = self.calculate_trending_score(article)
            
            total_score = (
                recency * self.weights['recency'] +
                source_auth * self.weights['source_authority'] +
                engagement * self.weights['engagement'] +
                quality * self.weights['content_quality'] +
                trending * self.weights['trending']
            )
            
            article['ranking_score'] = round(total_score * 100, 2)
            article['rank_metrics'] = {
                'recency': round(recency, 2),
                'source_authority': round(source_auth, 2),
                'engagement': round(engagement, 2),
                'content_quality': round(quality, 2),
                'trending': round(trending, 2)
            }
            article['rank'] = 0
            ranked_articles.append(article)
        
        ranked_articles.sort(key=lambda x: x['ranking_score'], reverse=True)
        for i, article in enumerate(ranked_articles, 1):
            article['rank'] = i
        return ranked_articles

def load_feeds():
    """Load RSS feeds from feeds.yaml"""
    with open("feeds.yaml", "r", encoding='utf-8') as f:
        return yaml.safe_load(f)["feeds"]

def fetch_articles(feed_config):
    """Fetch all articles from all feeds"""
    articles_by_theme = defaultdict(list)
    seen_links = set()
    ranker = ArticleRanker()
    
    for theme in feed_config:
        theme_articles = []
        for source in theme["sources"]:
            try:
                print(f"Fetching: {source['url']}")
                feed = feedparser.parse(source['url'])
                for entry in feed.entries[:20]:
                    if entry.link in seen_links:
                        continue
                    seen_links.add(entry.link)
                    
                    title = clean_text(fix_encoding(entry.get("title", "No title")))
                    summary = clean_text(fix_encoding(entry.get("summary", "No summary available")))
                    
                    pub_date = entry.get("published", None)
                    if pub_date:
                        try:
                            for fmt in ['%a, %d %b %Y %H:%M:%S %Z', '%Y-%m-%dT%H:%M:%SZ', '%Y-%m-%d %H:%M:%S']:
                                try:
                                    pub_datetime = datetime.strptime(pub_date, fmt)
                                    break
                                except ValueError:
                                    continue
                            else:
                                pub_datetime = datetime.now()
                        except:
                            pub_datetime = datetime.now()
                    else:
                        pub_datetime = datetime.now()
                    
                    theme_articles.append({
                        "title": title,
                        "link": entry.link,
                        "summary": summary,
                        "published": pub_date or datetime.now().strftime("%a, %d %b %Y %H:%M:%S %Z"),
                        "published_datetime": pub_datetime,
                        "source": urlparse(entry.link).netloc
                    })
            except Exception as e:
                print(f"Error fetching {source['url']}: {e}")
        
        ranked_articles = ranker.rank_articles(theme_articles)
        articles_by_theme[theme["name"]] = ranked_articles
    
    return articles_by_theme

def generate_html(articles_by_theme):
    """Generate static HTML pages using Jinja2 templates"""
    env = Environment(loader=FileSystemLoader(TEMPLATES_DIR))
    
    all_articles = []
    for theme, articles in articles_by_theme.items():
        for article in articles:
            article['theme'] = theme
        all_articles.extend(articles)
    
    all_articles.sort(key=lambda x: x['ranking_score'], reverse=True)
    top_10_articles = all_articles[:10]
    
    template = env.get_template("index.html")
    with open(os.path.join(SITE_DIR, "index.html"), "w", encoding="utf-8") as f:
        f.write(template.render(
            themes=articles_by_theme.keys(),
            top_articles=top_10_articles,
            articles_by_theme=articles_by_theme,
            last_built=datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")
        ))
    
    theme_template = env.get_template("theme.html")
    for theme, articles in articles_by_theme.items():
        filename = theme.lower().replace(" ", "_") + ".html"
        with open(os.path.join(SITE_DIR, filename), "w", encoding="utf-8") as f:
            f.write(theme_template.render(
                theme=theme,
                articles=articles,
                last_built=datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")
            ))

def main():
    """Main execution"""
    print(f"Starting build at {datetime.now()}")
    
    os.makedirs(SITE_DIR, exist_ok=True)
    
    feed_config = load_feeds()
    print(f"Loaded {len(feed_config)} themes")
    
    articles_by_theme = fetch_articles(feed_config)
    print(f"Fetched articles for {len(articles_by_theme)} themes")
    
    generate_html(articles_by_theme)
    print(f"Build complete! Output in {SITE_DIR}/")
    
    if os.path.exists(os.path.join(TEMPLATES_DIR, "styles.css")):
        import shutil
        shutil.copy(
            os.path.join(TEMPLATES_DIR, "styles.css"),
            os.path.join(SITE_DIR, "styles.css")
        )

if __name__ == "__main__":
    main()
