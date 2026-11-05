"""Comment sentiment analysis (advanced feature).

In Azure this calls Azure AI Language (Text Analytics) sentiment API when
AZURE_LANGUAGE_ENDPOINT and AZURE_LANGUAGE_KEY are set. Locally it falls back
to a small lexicon so the feature still works offline and in CI tests.
"""
import json
import os
import urllib.request

POS = {"love", "great", "amazing", "awesome", "good", "nice", "cool", "fun", "best", "wow", "beautiful", "funny"}
NEG = {"hate", "bad", "awful", "boring", "worst", "terrible", "ugly", "sad", "fake", "poor"}


def _local(text):
    words = {w.strip(".,!?").lower() for w in text.split()}
    score = len(words & POS) - len(words & NEG)
    return "positive" if score > 0 else "negative" if score < 0 else "neutral"


def analyse(text):
    ep, key = os.environ.get("AZURE_LANGUAGE_ENDPOINT"), os.environ.get("AZURE_LANGUAGE_KEY")
    if not (ep and key):
        return _local(text)
    body = json.dumps({"kind": "SentimentAnalysis",
                       "analysisInput": {"documents": [{"id": "1", "language": "en", "text": text}]}}).encode()
    req = urllib.request.Request(f"{ep.rstrip('/')}/language/:analyze-text?api-version=2023-04-01", data=body,
                                 headers={"Ocp-Apim-Subscription-Key": key, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=3) as r:
            return json.load(r)["results"]["documents"][0]["sentiment"]
    except Exception:
        return _local(text)  # degrade gracefully if the AI service is unavailable
