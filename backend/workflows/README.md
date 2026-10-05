# ComfyUI workflow templates

API-format ComfyUI graphs with `{{placeholder}}` strings. `app/comfy/workflows.py`
loads a template, replaces every placeholder (a string that is exactly `"{{name}}"`
becomes the typed value, e.g. a number), and refuses to send a graph with leftovers.

| File | Used for | Extra nodes needed |
|---|---|---|
| `txt2img.json` | character sheets, panels without characters, fallback | core only |
| `ipadapter_1ref.json` | panels with 1 character | ComfyUI_IPAdapter_plus |
| `ipadapter_2ref.json` | panels with 2+ characters (two refs, reduced weight) | ComfyUI_IPAdapter_plus |
| `inpaint.json` | repaint a masked region of a panel (Phase 4) | core only |
| `inpaint_ipadapter.json` | inpaint a region that contains a character, with its reference | ComfyUI_IPAdapter_plus |

Placeholders: `checkpoint, width, height, prompt, negative_prompt, seed, steps, cfg,
sampler, scheduler, filename_prefix, ipadapter_preset, ipadapter_weight,
ipadapter_weight_2, ipadapter_end_at, reference_image_1, reference_image_2`; inpainting adds
`init_image, mask_image, denoise, mask_grow, mask_feather`.

To use your own graph: build it in ComfyUI, "Save (API format)", put the placeholders in,
save it here and point `COMFYUI_WORKFLOW_DIR` / the file names in code at it.
