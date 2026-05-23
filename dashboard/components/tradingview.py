import streamlit as st


def tradingview_chart(symbol: str = "AAPL", height: int = 600):
    """
    Renders the TradingView Advanced Chart Widget.
    Pro account session persists via the iframe — user stays logged in
    with their saved layouts and custom indicators.
    """
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
      <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ background: #0f1117; overflow: hidden; }}
        #tv_chart {{ width: 100%; height: {height}px; }}
        .expand-btn {{
          position: absolute; top: 8px; right: 8px; z-index: 999;
          background: rgba(30,37,50,0.85); border: 1px solid #334155;
          color: #94a3b8; border-radius: 4px; padding: 4px 8px;
          cursor: pointer; font-size: 12px;
        }}
        .expand-btn:hover {{ color: #e2e8f0; border-color: #7c3aed; }}
      </style>
    </head>
    <body>
      <button class="expand-btn" onclick="toggleFullscreen()" title="Toggle fullscreen (F)">⤢</button>
      <div id="tv_chart"></div>
      <script type="text/javascript" src="https://s3.tradingview.com/tv.js"></script>
      <script>
        new TradingView.widget({{
          "autosize": true,
          "symbol": "{symbol}",
          "interval": "D",
          "timezone": "America/New_York",
          "theme": "dark",
          "style": "1",
          "locale": "en",
          "toolbar_bg": "#0f1117",
          "enable_publishing": false,
          "allow_symbol_change": true,
          "save_image": true,
          "container_id": "tv_chart",
          "hide_side_toolbar": false,
          "studies": [],
          "show_popup_button": true
        }});

        function toggleFullscreen() {{
          const el = document.getElementById('tv_chart');
          if (!document.fullscreenElement) {{
            el.requestFullscreen().catch(() => {{}});
          }} else {{
            document.exitFullscreen();
          }}
        }}

        document.addEventListener('keydown', (e) => {{
          if (e.key === 'f' || e.key === 'F') toggleFullscreen();
        }});
      </script>
    </body>
    </html>
    """
    st.iframe(html, height=height)
