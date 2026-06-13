from core.news_filter import clean_hype_language, filter_and_format_news, format_filtered_news_to_markdown

# Keep existing function interface for backward compatibility if any
def filter_news(news):
    return filter_and_format_news(news)