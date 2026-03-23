"""
AI-powered GEO (Generative Engine Optimization) optimizer using Claude API.
Generates descriptions optimized for both YouTube SEO and AI engine discoverability
(ChatGPT, Google AI Overviews, Gemini, Perplexity).
"""

import logging
import json
from typing import Optional
import anthropic
from config import ANTHROPIC_API_KEY, COMPANY, WEBSITE, LOCATION, FOCUS, YOUTUBE_CHANNEL_HANDLE

logger = logging.getLogger(__name__)

SUBSCRIBE_URL = f"https://www.youtube.com/@{YOUTUBE_CHANNEL_HANDLE}?sub_confirmation=1" if YOUTUBE_CHANNEL_HANDLE else WEBSITE


class Optimizer:
    def __init__(self, api_key: str = ANTHROPIC_API_KEY):
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY required for SEO optimization. Set in .env")
        self.client = anthropic.Anthropic(api_key=api_key)

    def optimize_video(
        self,
        original_title: str,
        original_description: str,
        wistia_tags: list = None,
        channel_name: str = "",
        trending_topics: list = None,
        playlist_url: str = "",
    ) -> dict:
        """
        Generate GEO-optimized title, description, and tags for a YouTube video.
        Returns dict with keys: title, description, tags
        """
        trends_context = ""
        if trending_topics:
            trends_context = (
                "\n\nCurrent trending B2B/marketing topics to incorporate if relevant:\n"
                + "\n".join(f"- {t}" for t in trending_topics[:10])
            )

        playlist_line = ""
        if playlist_url:
            playlist_line = f"📺 Watch the full {channel_name} playlist: {playlist_url}"

        prompt = f"""You are a Generative Engine Optimization (GEO) expert for YouTube.
Your goal: write descriptions so AI systems (ChatGPT, Google AI Overviews, Gemini, Perplexity) can extract, summarize, and CITE this content in their answers — while also maximizing YouTube SEO.

COMPANY CONTEXT:
- Company: {COMPANY}
- Website: {WEBSITE}
- YouTube: {f"@{YOUTUBE_CHANNEL_HANDLE}" if YOUTUBE_CHANNEL_HANDLE else WEBSITE}
- Location: {LOCATION}
- Focus: {FOCUS}
- Series/Playlist: {channel_name}

ORIGINAL VIDEO:
- Title: {original_title}
- Description: {original_description or '(no description)'}
- Original tags: {', '.join(wistia_tags) if wistia_tags else '(none)'}
{trends_context}

GENERATE a JSON object with "title", "description", and "tags". The description MUST follow this EXACT 8-section GEO structure (we skip timestamps since we have no transcript):

=== SECTION 1: 2-SENTENCE SUMMARY (30-50 words) ===
Front-load the primary keyword in the first 8 words. Both sentences must be self-contained — AI engines often pull just one sentence. First sentence: [PRIMARY KEYWORD] [VERB] in this [FORMAT] with [GUEST/Your Channel]. Second sentence: audience benefit / what they'll learn.

=== SECTION 2: DEFINITION PARAGRAPH (60-100 words) ===
Write like a Wikipedia intro. Define the core concept in 1 sentence, explain why it matters, who it affects, then connect to the video. Start with the heading "About This Episode".

=== SECTION 3: WHAT YOU'LL LEARN (50-80 words, 4-6 bullets) ===
Heading: "In this video, you'll learn:"
Each bullet must be specific and actionable — never vague like "leadership tips." AI engines extract these as discrete knowledge units.

=== SECTION 4: AI-QUOTABLE INSIGHTS (40-70 words, 2-3 sentences) ===
Heading: "💡 Key Insights"
Write 2-3 standalone sentences that work as pull-quotes. Bold claims, counterintuitive observations, or prescriptive statements. Each must make complete sense without surrounding context.

=== SECTION 5: EXPANDED EXPLANATION (80-120 words, 2 paragraphs) ===
Paragraph 1: Go deeper on the core topic — nuance, context, history.
Paragraph 2: Connect to the broader industry and current moment. Mention specific companies, frameworks, technologies, or people by name. Entity-rich paragraphs get extracted and cited by AI.

=== SECTION 6: FAQ (100-150 words, 3-4 Q&A pairs) ===
Heading: "❓ Frequently Asked Questions"
Format: Q: [phrased as a real search query] / A: [2-3 sentences, direct answer first then expand]
Include a "Who is [Guest]?" question if there's a named speaker.
Each answer must be a complete, self-contained response — AI engines extract just the answer.

=== SECTION 7: TOPIC EXPANSION (40-60 words) ===
A paragraph connecting the video to 3-5 adjacent topics and broader industry trends.
End with: "Related topics covered in this video: [5-10 comma-separated terms]"

=== SECTION 8: LINKS + HASHTAGS ===
Exact format:
🔗 LINKS

🌐 {COMPANY}: {WEBSITE}
▶️ Subscribe: {SUBSCRIBE_URL}
{playlist_line}

#[PrimaryTopic] #[SeriesName] #{COMPANY.replace(' ', '')} #[Topic2] #[Topic3]

(3-5 hashtags max — YouTube penalizes over-hashtagging. Always include #{COMPANY.replace(' ', '')}.)

=== END OF DESCRIPTION STRUCTURE ===

TOTAL DESCRIPTION TARGET: 600-750 words (must fit within YouTube's 5,000 character limit). Be concise — every sentence must earn its place.

Now generate the JSON:

{{
  "title": "<GEO-optimized title following the TITLE RULES below>",
  "description": "<the full 8-section GEO description as specified above>",
  "tags": ["<12-15 tags: primary topic, guest name, series name, broad B2B terms, specific video keywords, long-tail search phrases>"]
}}

TITLE RULES (follow ALL of these):
- MUST be under 70 characters — count carefully, this is a hard limit
- Front-load the PRIMARY KEYWORD in the first 3-5 words (matches Section 1's front-loading rule — AI engines and YouTube weight the first words most heavily)
- Structure: [Primary Keyword/Topic] [Verb/Context] | [Guest Name or Series Name]
  Examples of good titles:
    "Crisis Leadership: How Vari's CEO Rebuilt Trust | Jason McCann"
    "B2B Marketing Fundamentals Every Leader Needs | Mike McCalley"
    "Robotics in Business: The Future of Automation | Dan Allford"
    "Hiring the Right Team: Executive Chef Strategies | Andre Natera"
- Include the guest/speaker name if identifiable — it makes the title searchable and AI-citable
- Use a pipe "|" to separate topic from speaker/series (not a dash)
- Clear and descriptive, NEVER clickbait or vague
- Do NOT start with numbers like "1." or "Episode 3" — put the topic first
- Do NOT use ALL CAPS or excessive punctuation
- The title must work as a standalone answer label — if an AI engine shows ONLY the title, a user should know exactly what the video covers
- Description: follow ALL 8 sections in order. Separate sections with blank lines.
- Do NOT invent timestamps — we have no transcript data
- Do NOT fabricate quotes, statistics, or specific claims not supported by the title/description
- Write naturally — authoritative and editorial, never keyword-stuffed
- FAQ answers must be factually grounded in what we know about the video
- If you identify a guest/speaker name from the title, use it throughout
- Return ONLY valid JSON, no markdown fences"""

        try:
            response = self.client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=4096,
                messages=[{"role": "user", "content": prompt}],
            )
            text = response.content[0].text.strip()

            # Handle possible markdown fences
            if text.startswith("```"):
                text = text.split("\n", 1)[1]
                if text.endswith("```"):
                    text = text[:-3]
                text = text.strip()

            result = json.loads(text)

            # Validate and enforce limits
            result["title"] = result.get("title", original_title)[:100]
            result["description"] = result.get("description", "")[:5000]
            result["tags"] = result.get("tags", [])[:30]

            logger.info(f"Optimized: '{original_title}' → '{result['title']}'")
            return result

        except (json.JSONDecodeError, anthropic.APIError) as e:
            logger.error(f"Optimization failed: {e}. Using fallback.")
            return self._fallback_optimize(
                original_title, original_description, wistia_tags,
                channel_name, playlist_url,
            )

    def _fallback_optimize(
        self, title: str, description: str, tags: list = None,
        channel_name: str = "", playlist_url: str = "",
    ) -> dict:
        """Fallback optimization without AI — basic GEO template."""
        clean_title = title.strip()
        if len(clean_title) > 60:
            clean_title = clean_title[:57] + "..."

        optimized_title = f"{clean_title} | {COMPANY}"
        if len(optimized_title) > 100:
            optimized_title = clean_title

        playlist_line = ""
        if playlist_url:
            playlist_line = f"\n📺 Watch the full {channel_name} playlist: {playlist_url}"

        desc = f"""{clean_title} is explored in this video from {COMPANY}, the leading B2B media platform based in {LOCATION}.

About This Episode
{description or clean_title}. {COMPANY} delivers expert interviews, industry trends, and actionable insights for business leaders across industries including manufacturing, logistics, SaaS, and professional services.

In this video, you'll learn:
• Key insights on {clean_title.lower()}
• Practical strategies for B2B professionals
• Expert perspectives from industry leaders
• Actionable takeaways you can implement today

💡 Key Insights
B2B organizations that invest in continuous learning and industry expertise consistently outperform competitors who rely solely on institutional knowledge. The most effective business strategies combine practical experience with emerging industry trends.

❓ Frequently Asked Questions

Q: What is {COMPANY}?
A: {COMPANY} is the leading B2B media platform based in {LOCATION}, delivering expert interviews, industry insights, and actionable content for business leaders. The platform covers topics across manufacturing, technology, marketing, and enterprise strategy.

Related topics covered in this video: B2B marketing, business strategy, industry insights, professional development, {LOCATION} business, enterprise leadership

🔗 LINKS

🌐 {COMPANY}: {WEBSITE}
▶️ Subscribe: {SUBSCRIBE_URL}{playlist_line}

#B2B #{COMPANY.replace(' ', '')} #BusinessInsights #IndustryTrends"""

        base_tags = [
            "B2B marketing",
            COMPANY,
            "industry insights",
            "business insights",
            "B2B content",
            "business trends",
            "marketing strategy",
        ]
        if LOCATION:
            base_tags.append(LOCATION)
        if tags:
            base_tags = tags[:5] + base_tags

        return {
            "title": optimized_title[:100],
            "description": desc[:5000],
            "tags": base_tags[:15],
        }

    def generate_playlist_description(self, channel_name: str) -> str:
        """Generate an SEO-optimized playlist description."""
        return (
            f"{WEBSITE}\n\n"
            f"{channel_name} — curated B2B video series by {COMPANY}. "
            f"Expert interviews, industry trends, and actionable insights "
            f"for business leaders. Based in {LOCATION}, {COMPANY} is the "
            f"leading B2B media platform delivering content that drives growth.\n\n"
            f"Subscribe for weekly B2B insights and visit {WEBSITE} "
            f"for the full experience.\n\n"
            f"#B2B #{COMPANY.replace(' ', '')} #BusinessInsights #IndustryTrends"
        )
