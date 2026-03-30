from transformers import AutoTokenizer

tokenizer = AutoTokenizer.from_pretrained("Qwen/Qwen2-7B")

text = "你是谁？"

tokens = tokenizer.tokenize(text)
token_ids = tokenizer.encode(text)

print("tokens:", tokens)
print("token_ids:", token_ids)
print("token_count:", len(token_ids))
