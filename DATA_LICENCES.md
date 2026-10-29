# Data licences

## Olist Brazilian E-Commerce Public Dataset
- **Source:** Olist, "Brazilian E-Commerce Public Dataset by Olist", Kaggle `olistbr/brazilian-ecommerce`
  — https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce
- **Licence:** Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International (**CC BY-NC-SA 4.0**)
  — https://creativecommons.org/licenses/by-nc-sa/4.0/
- **Credit line:** "Contains data from the Brazilian E-Commerce Public Dataset by Olist (Kaggle), licensed under
  CC BY-NC-SA 4.0."
- **Where it is used:** ShopNova's real orders (task T15). The raw files are downloaded by hand into
  `data/raw/olist/` and are **not** in git. The processed sample in `callverse/data/real/`
  (`shopnova_olist_sample.json`, built by `scripts/build_shopnova_sample.py`) is **derived from Olist and keeps the
  same licence (CC BY-NC-SA 4.0)**.
- **Changes made:** only electronics orders, 2,000 orders sampled, dates moved to 2026, prices converted from BRL to
  TND, statuses mapped, review texts removed; client names, emails, phones, product names, stock, carriers, tracking
  numbers and refunds are generated (see `docs/platform_contract.md` §2).
- **Use:** non-commercial university use only (CallVerse, a university data-science project).
