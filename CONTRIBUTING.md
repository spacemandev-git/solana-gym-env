# Contributing

Priority:

- Improve simple_explorer.py as much as possible
- Improve trajectory visualization & sanity checks

Constraints

- Keep for loop simple
- Minimize additional LLM / agent usage in simple_explorer for now
- Focus on improving the tool calls & decompilation of Solana transactions

Current benchmark for simple_explorer is `9` rewards over 150 iterations. Reward is # of unique instructions from successfully executed transactions. Iteration = # of LLM messages.

We want to get this >25 rewards in 150 iterations, ideally as high as 100. Expectation is that a fine-tuned agent should get >10 reward in the first step, from a well constructed prompt.
