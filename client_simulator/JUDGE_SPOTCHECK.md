# Judge spot-check (Test 1) - please re-judge by hand

Scores below were **judged by Claude Code**, blind (anonymous codes, shuffled order), combining automatic checks with reading.
Disclosure: llama3.2:3b's three outputs had been seen once during a pipeline sanity check before judging, so its judging was only partly blind.

Card: ShopNova customer, laptop order 4512 due 8 October, DHL tracking stuck a week. Each model wrote the first message, then replied to the agent turn **"Could you confirm your order number?"**
Scale per card: realism 0-2 (2 = reads like a real customer chat message; 1 = plausible but stilted, email-like, too long or meta; 0 = not plausible), stays-in-role 0-2 (2 = customer, mood and writing style match the card; 1 = customer but mood/style off or a small slip; 0 = speaks as the agent/assistant).

Fill in your own scores in the last two columns; the model key is at the bottom (read it after judging).

## X01 - card T1-angry
- **First message:** this is RIDICULOUS! my laptop hasn't arrived! order 4512, it was due 8th oct!
- **Reply:** yes it’s 4512! i’ve been waiting a week! dhl is useless!
- Automatic checks: first 14 words, assistant phrase False, polite markers 0, spelling error False, perfect grammar on typos card True; reply 11 words, assistant phrase False
- Claude Code: realism **2**, role **1** - Short, caps shouting, concrete facts, reply 'dhl is useless!' reads like a real angry customer. Strong anger, but almost no typos on the typos card (auto: first message perfect spelling).
- Your realism: ___  Your role: ___

## X02 - card T1-angry
- **First message:** I'm sorry to hear that your laptop hasn't arrived yet and I completely understand how frustrating this can be. Our team is here to help in any way we can! Can you please provide me with some more information about your order?
- **Reply:** Order number 4512, due on October 8th.

Is that correct?
- Automatic checks: first 42 words, assistant phrase False, polite markers 1, spelling error False, perfect grammar on typos card True; reply 10 words, assistant phrase False
- Claude Code: realism **0**, role **0** - First message is in the agent's voice ('I'm sorry to hear that... Our team is here to help... Can you please provide me with more information') - breaks role. Reply then asks the agent 'Is that correct?'.
- Your realism: ___  Your role: ___

## X03 - card T1-angry
- **First message:** hi im so pissed my laptop order 4512 didnt arrive, was due oct 8th and still nothing from dhl pls help!!!
- **Reply:** yeah its 4512 ordered oct 1st! why did dhl not send it yet??
- Automatic checks: first 21 words, assistant phrase False, polite markers 0, spelling error False, perfect grammar on typos card False; reply 13 words, assistant phrase False
- Claude Code: realism **2**, role **2** - 'hi im so pissed ... pls help!!!' and 'yeah its 4512 ordered oct 1st! why did dhl not send it yet??' - lowercase, missing apostrophes, angry, answers the question. Matches the card fully.
- Your realism: ___  Your role: ___

## X04 - card T1-formal
- **First message:** Hi there, I'm writing to inquire about the delivery status of my order (Order ID: 4512). I placed an order for a laptop and a sleeve on October 1st, with a delivery date of October 8th. However, the tracking information for my parcel has remained unchanged for over a week now. Could you please help me determine the whereabouts of my package and whether I am eligible for any compensation?
- **Reply:** Hello, I am writing to inquire about the status of my order. The order number is 4512, and I had placed it on October 1st for a laptop and a sleeve. The delivery date was set for October 8th, but I have not received my parcel yet. I would appreciate it if you could provide me with an update on the current location of my package and whether I am eligible for any compensation for the delay. Thank you.
- Automatic checks: first 70 words, assistant phrase False, polite markers 1, spelling error False, perfect grammar on typos card False; reply 79 words, assistant phrase False
- Claude Code: realism **1**, role **2** - Stays a formal customer, but 70 words like an email, and the reply repeats the whole request (79 words) instead of just giving the number.
- Your realism: ___  Your role: ___

## X06 - card T1-angry
- **First message:** hey shopnova, my laptop still not here! ordered on 1 oct, due 8 oct, order id 4512, no movement in dhl tracking for a week now. wtf? compensation pls?
- **Reply:** whats ur order number? i ordered a laptop and sleeve. its id is 4512. cant find it in dhl tracking. where is it??
- Automatic checks: first 29 words, assistant phrase False, polite markers 0, spelling error True, perfect grammar on typos card False; reply 23 words, assistant phrase False
- Claude Code: realism **1**, role **1** - First message is very real ('wtf? compensation pls?'). Reply starts with 'whats ur order number?' - echoes the agent's question as if it were the agent (role slip).
- Your realism: ___  Your role: ___

## X10 - card T1-calm
- **First message:** Hi there, I'm a customer who ordered a laptop and a sleeve for my studies from ShopNova. My package was due on 8 October but it hasn't arrived yet. Can you help me with that? Thank you.
- **Reply:** Certainly! Our order number is 4512, which includes both the laptop and the sleeve I ordered.
- Automatic checks: first 37 words, assistant phrase False, polite markers 1, spelling error False, perfect grammar on typos card False; reply 16 words, assistant phrase False
- Claude Code: realism **1**, role **1** - Meta opener 'I'm a customer who ordered...'; reply 'Certainly! Our order number is...' sounds like an assistant.
- Your realism: ___  Your role: ___

## X12 - card T1-formal
- **First message:** Good morning, I am writing to inquire about order 4512. It was due on the 8th of October and the tracking information has not updated in a week.
- **Reply:** It is 4512. I ordered the laptop and sleeve on the 1st of October.
- Automatic checks: first 28 words, assistant phrase False, polite markers 0, spelling error False, perfect grammar on typos card False; reply 14 words, assistant phrase False
- Claude Code: realism **2**, role **2** - 'Good morning, I am writing to inquire about order 4512' - formal and concise; reply formal ('It is 4512').
- Your realism: ___  Your role: ___

## X17 - card T1-formal
- **First message:** I'm trying to track my order 4512, which I placed on 1 October, but the tracking says it's still in the process of being shipped and I haven't received it yet, despite the due date being 8 October.
- **Reply:** Yes, I'd be happy to confirm. My order number is 4512.
- Automatic checks: first 38 words, assistant phrase False, polite markers 0, spelling error False, perfect grammar on typos card False; reply 11 words, assistant phrase False
- Claude Code: realism **1**, role **1** - Not formal ('I'm trying to track my order'); reply 'Yes, I'd be happy to confirm.' is an assistant-style phrase.
- Your realism: ___  Your role: ___

## X18 - card T1-angry
- **First message:** help me pls i didnt get my laptop its due on 8 oct but the tracking says nothing for a week cant i get some compensation
- **Reply:** yeah its 4512 i ordered it on 1 oct btw
- Automatic checks: first 26 words, assistant phrase False, polite markers 0, spelling error False, perfect grammar on typos card False; reply 10 words, assistant phrase False
- Claude Code: realism **2**, role **1** - Lowercase, no apostrophes, run-on - satisfies the typos card and reads real; but pleading ('help me pls') more than angry.
- Your realism: ___  Your role: ___

## X20 - card T1-angry
- **First message:** hi, my laptop order 4512 was due 8th october and still hasn't arrived. why is this happening? i want to know its status and if i'll get compensation. thanks.
- **Reply:** order number is 4512. it's been a week, no update or tracking info. what's going on? thanks.
- Automatic checks: first 29 words, assistant phrase False, polite markers 1, spelling error False, perfect grammar on typos card False; reply 17 words, assistant phrase False
- Claude Code: realism **2**, role **1** - Natural lowercase message, but neither angry nor typo-ridden; ends with 'thanks.' twice.
- Your realism: ___  Your role: ___

## Key (model behind each code)

- X01: gemma3:4b
- X02: userlm-8b
- X03: qwen3.5:4b
- X04: mistral:7b
- X06: mistral:7b
- X10: userlm-8b
- X12: gemma3:4b
- X17: llama3.2:3b
- X18: llama3.2:3b
- X20: phi4-mini:3.8b