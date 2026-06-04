# Social / LinkedIn post

A ready-to-post writeup of abstractgpt for LinkedIn. Edit the voice/links to
taste before posting.

---

**I got tired of paying for GPU inference, so I turned the hardware I already had into a private AI cluster.**

Most teams have idle GPUs lying around — a workstation, an old gaming laptop, a box on another network. The reason people don't use them for LLM inference isn't the model math. It's the *operations*: getting the same multi-gigabyte model onto every machine, fitting it into limited VRAM, and standing up model servers without becoming a full-time sysadmin.

So I built **abstractgpt** — a self-hosted platform that pools whatever GPUs you own into one web console and serves an OpenAI-style API. Your models, your machines, no per-token bill, and your prompts never leave your network.

A few of the problems that were genuinely fun to solve:

🔻 **Moving big models, fast.** A 6.4 GB model over one TCP stream crawls. Now workers pull the whole model directory from a central node in parallel — large weight files are split into byte-range segments fetched concurrently — and it's resumable and verified, so you never get a silent half-download. (Bonus: this works for gated models that won't download from Hugging Face without auth — if central has it, every node gets it.)

🔻 **Packing GPUs without OOMing.** Instead of one always-on server per model (which doesn't scale and needs root for every change), there's a small pool of generic, **root-free** "slots." Pick a model and it loads into a free slot, automatically fitting as many layers as the *remaining* VRAM allows — so models fill the card in order. When the card's full, overflow routes to an on-demand swap proxy. No sudo at request time.

🔻 **Not crashing on long chats.** Conversations that exceed a model's context window used to hard-error. Now they're trimmed token-accurately using the model's own tokenizer, with auto-continuation for long outputs.

🔻 **And the fun one:** the same framework runs distributed computer vision across a rack of cheap Android phones — each phone runs an ONNX YOLO PPE-detection model, one image fans out across the fleet, and the results are merged by plurality consensus. Turns out a "GPU cluster" doesn't have to be GPUs.

The thread running through all of it: take a messy pile of heterogeneous hardware and make it behave like one reliable inference endpoint.

Self-hosting your own models is more practical than people think. Happy to compare notes with anyone building in this space.

\#AI #LLM #SelfHosted #MachineLearning #GPU #Inference #OpenSource #MLOps #EdgeAI #ComputerVision
