#!/usr/bin/env python3
import os
import yaml
import feedparser
import json
from datetime import datetime
from collections import defaultdict
from jinja2 import Environment, FileSystemLoader
from urllib.parse import urlparse

# Configuration
SITE_DIR = "site"
TEMPLATES_DIR = "templates"

def load_feeds():
    """Load RSS feeds from feeds.yaml"""
    with open("feeds.yaml", "r") as f:
        return yaml.safe_load(f)["feeds"]

def fetch_articles(feed_config):
    """Fetch all articles from all feeds"""
    articles_by_theme = defaultdict(list)
    seen_links = set()  # For deduplication
    
    for theme in feed_config:
        for source in theme["sources"]:
            try:
                feed = feedparser.parse(source["url"])
                for entry in feed.entries[:20]:  # Limit to 20 per source
                    # Skip duplicates
                    if entry.link in seen_links:
                        continue
                    seen_links.add(entry.link)
                    
                    articles_by_theme[theme["name"]].append({
                        "title": entry.get("title", "No title"),
                        "link": entry.link,
                        "summary": entry.get("summary", "No summary available"),
                        "published": entry.get("published", datetime.now().strftime("%a, %d %b %Y %H:%M:%S %Z")),
                        "source": urlparse(entry.link).netloc
                    })
            except Exception as e:
                print(f"Error fetching {source['url']}: {e}")
    
    return articles_by_theme

def generate_html(articles_by_theme):
    """Generate static HTML pages using Jinja2 templates"""
    env = Environment(loader=FileSystemLoader(TEMPLATES_DIR))
    
    # Generate the main index page
    template = env.get_template("index.html")
    with open(os.path.join(SITE_DIR, "index.html"), "w") as f:
        f.write(template.render(
            themes=articles_by_theme.keys(),
            last_built=datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")
        ))
    
    # Generate individual theme pages
    theme_template = env.get_template("theme.html")
    for theme, articles in articles_by_theme.items():
        # Create a safe filename from the theme name
        filename = theme.lower().replace(" ", "_") + ".html"
        with open(os.path.join(SITE_DIR, filename), "w") as f:
            f.write(theme_template.render(
                theme=theme,
                articles=articles,
                last_built=datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")
            ))

def main():
    """Main execution"""
    print(f"Starting build at {datetime.now()}")
    
    # Create site directory if it doesn't exist
    os.makedirs(SITE_DIR, exist_ok=True)
    
    # Load feeds and fetch articles
    feed_config = load_feeds()
    print(f"Loaded {len(feed_config)} themes")
    
    articles_by_theme = fetch_articles(feed_config)
    print(f"Fetched articles for {len(articles_by_theme)} themes")
    
    # Generate HTML
    generate_html(articles_by_theme)
    print(f"Build complete! Output in {SITE_DIR}/")
    
    # Copy static assets (CSS, etc.)
    os.system(f"cp {TEMPLATES_DIR}/styles.css {SITE_DIR}/ 2>/dev/null || true")

if __name__ == "__main__":
    main()
