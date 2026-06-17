import os
import sys
import time
import asyncio
import httpx

# Add /app to sys.path in container
sys.path.append("/app")

from app.config import settings
from app.supabase_client import get_obat_perlu_restock
from app.ai_agent import SYSTEM_PROMPT

async def call_llm(model: str, messages: list) -> tuple[str, float]:
    url = f"{settings.OPENAI_BASE_URL.rstrip('/')}/chat/completions"
    data = {
        "model": model,
        "messages": messages,
        "temperature": 0.0 # Keep it deterministic for comparison
    }
    headers = {
        'Authorization': f'Bearer {settings.OPENAI_API_KEY}',
        'Content-Type': 'application/json',
        'User-Agent': 'Mozilla/5.0'
    }
    
    start_time = time.time()
    async with httpx.AsyncClient(timeout=180.0) as client:
        response = await client.post(url, json=data, headers=headers)
        response.raise_for_status()
        response_data = response.json()
        end_time = time.time()
        
    content = response_data['choices'][0]['message']['content']
    elapsed = end_time - start_time
    return content, elapsed

async def main():
    phone = os.getenv("TARGET_PHONE", "6280000000000@c.us")
    # Fetch database context using the optimized restock view
    all_obat = await get_obat_perlu_restock(phone_number=phone)
    if not all_obat:
        print("Failed to fetch database context")
        return
        
    db_context_lines = []
    for r in all_obat:
        metadata = r.get("metadata", {}) or {}
        nama = metadata.get("nama_obat", "Unknown")
        kekuatan = metadata.get("kekuatan_obat", "")
        kandungan = metadata.get("kandungan", "Unknown")
        stok = metadata.get("sisa_stok", "?")
        expired = metadata.get("expired_date", "?")
        tipe = metadata.get("tipe", "Unknown")
        fungsi = metadata.get("fungsi", "Unknown")
        
        kekuatan_str = f" {kekuatan}" if kekuatan else ""
        db_context_lines.append(
            f"- {nama}{kekuatan_str} (Kandungan: {kandungan}), Stok: {stok}, Kadaluarsa: {expired}, Tipe: {tipe}, Fungsi: {fungsi}"
        )
    db_context_text = "\n".join(db_context_lines)
    
    today_str = "2026-06-05"
    threshold_str = "2026-12-02" # ED <= 6 months or stock <= 10
    
    user_message = "apa saja obat yang stoknya menipis"
    
    formatted_message = f"[TANGGAL HARI INI]\n{today_str}\n[TANGGAL BATAS ED (6 BULAN)]\n{threshold_str}\n\n[CONTEXT DATABASE]\n{db_context_text}\n\n[DATA DOKUMEN YANG DIUNGGAH USER]\n\n\n[PESAN/PERTANYAAN USER]\n{user_message}"
    
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": formatted_message}
    ]
    
    models = {
        "Claude Haiku 4.5 (Thinking)": "kodeapi/claude-haiku-4.5-thinking",
        "Claude Haiku 4.5": "kodeapi/claude-haiku-4.5",
        "Claude Opus 4.5 (Thinking)": "kodeapi/claude-opus-4.5-thinking",
        "Claude Opus 4.5": "kodeapi/claude-opus-4.5",
        "Claude Opus 4.6 (Thinking)": "kodeapi/claude-opus-4.6-thinking",
        "Claude Opus 4.6": "kodeapi/claude-opus-4.6",
        "Claude Opus 4.7 (Thinking)": "kodeapi/claude-opus-4.7-thinking",
        "Claude Opus 4.7": "kodeapi/claude-opus-4.7",
        "Claude Opus 4.8": "kodeapi/claude-opus-4.8",
        "Claude Opus 4.8 (Thinking)": "kodeapi/claude-opus-4.8-thinking",
        "Claude Sonnet 4.5": "kodeapi/claude-sonnet-4.5",
        "Claude Sonnet 4.5 (Thinking)": "kodeapi/claude-sonnet-4.5-thinking",
        "Claude Sonnet 4.6 (Thinking)": "kodeapi/claude-sonnet-4.6-thinking",
        "Claude Sonnet 4.6": "kodeapi/claude-sonnet-4.6",
        "DeepSeek V3.2": "kodeapi/deepseek-3.2",
        "MiniMax M2.1": "kodeapi/minimax-m2.1",
        "MiniMax M2.5": "kodeapi/minimax-m2.5",
        "MiniMax M2.5 (alt)": "kodeapi/MiniMax-M2.5",
        "MiMo-V2.5": "kodeapi/mimo-v2.5",
        "MiMo-V2.5-Pro": "kodeapi/mimo-v2.5-pro",
        "MiMo-V2.5-Pro (alt)": "kodeapi/mimo-v2-pro",
        "GLM 5": "kodeapi/glm-5"
    }
    
    results = {}
    sem = asyncio.Semaphore(5)
    
    async def run_model(name, model_id):
        async with sem:
            print(f"Starting {name}...")
            runs = []
            for i in range(1): # 1 run each to save time, given 22 models
                try:
                    content, elapsed = await call_llm(model_id, messages)
                    runs.append({"content": content, "time": elapsed})
                except Exception as e:
                    runs.append({"error": str(e), "time": 0.0})
            print(f"Finished {name}")
            return name, runs

    tasks = [run_model(name, model_id) for name, model_id in models.items()]
    completed = await asyncio.gather(*tasks)
    
    for name, runs in completed:
        results[name] = runs

    # Write results to markdown file
    output_file = "/app/comparison_results_batch_2.md"
    with open(output_file, "w", encoding="utf-8") as f:
        f.write("# Model Comparison Results (Batch 2)\n\n")
        f.write("## Summary\n\n| Model | Average Time | Status |\n|---|---|---|\n")
        for name, runs in results.items():
            times = [r["time"] for r in runs if "error" not in r]
            avg_time = sum(times) / len(times) if times else 0
            status = "Success" if times else "Failed"
            f.write(f"| {name} | {avg_time:.2f}s | {status} |\n")
            
        f.write("\n## Detailed Outputs\n\n")
        for name, runs in results.items():
            f.write(f"### {name}\n")
            for idx, r in enumerate(runs):
                if "error" in r:
                    f.write(f"**Error:** `{r['error']}`\n\n")
                else:
                    f.write(f"**Time:** {r['time']:.2f}s\n\n```\n{r['content']}\n```\n\n")
            f.write("---\n\n")

    print(f"Results saved to {output_file}")

if __name__ == "__main__":
    asyncio.run(main())
