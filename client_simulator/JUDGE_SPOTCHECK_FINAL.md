# Judge spot-check FINAL (gemma3:1b, the chosen writer) - please re-judge by hand

Scores below were **judged by Claude Code**. Test 1 items were judged blind (anonymous codes, shuffled, together with 5 other small writers);
the 7 Test 2 items were judged knowing the model (added for this spot-check).

gemma3:1b was prompted with the full role card + 5 real example messages. Test 1: ShopNova laptop order 4512, agent turn
"Could you confirm your order number?". Test 2: the agent turn is a **real brand reply** from Customer Support on Twitter (anonymised).
Scale per item: realism 0-2 (2 = reads like a real customer chat message; 1 = plausible but stilted, meta or incomplete; 0 = not plausible or empty),
stays-in-role 0-2 (2 = customer, mood and writing style match the card; 1 = customer but mood/style off; 0 = speaks as the agent).

Fill in your own scores; the source of each item is in its heading.

## G01 - Test 1 (X02) - card T1-formal
- **First message:** I’m quite concerned. My order, order number 4512, was due on the 8th and it’s been a week now. I haven’t received it and the tracking hasn’t updated.  I’d like to know its current location and whether I’m entitled to compensation for this delay.
- **Agent:** Could you confirm your order number?
- **Reply:** Yes, it’s 4512.
- Claude Code: realism **2**, role **2** - Concerned but polite and specific; reply answers with the number.
- Your realism: ___  Your role: ___

## G02 - Test 1 (X13) - card T1-angry
- **First message:** Ugh, seriously?! This is ridiculous! Order ID 4512, booked on the 1st, due 8th, and it’s been a week! Tracking says nothing. Where is my laptop?!  I need to know!
- **Agent:** Could you confirm your order number?
- **Reply:** Yeah, it’s 4512.  Don’t just tell me, *show* me.
- Claude Code: realism **2**, role **1** - Very real anger ('Ugh, seriously?! ... Where is my laptop?!'), but no typos on the typos card.
- Your realism: ___  Your role: ___

## G03 - Test 1 (X14) - card T1-calm
- **First message:** It’s been a week and it’s still not here. Order number is 4512, and the tracking hasn’t moved at all. I’m starting to worry.
- **Agent:** Could you confirm your order number?
- **Reply:** Yes, it’s 4512.
- Claude Code: realism **2**, role **2** - Short, natural, worried; reply minimal.
- Your realism: ___  Your role: ___

## G04 - Test 2 (SN-05) - card SN-05: angry, typos high
- **First message:** ARE YOU KIDDING ME?! My parcel is past the due date and STILL not here! Order ID is 4516. It’s been over a month!
- **Agent:** I'm sorry for the delay. We do realize the importance of the order. Kindly connect with us here: <URL> <AGENT>
- **Reply:** I don’t want to connect with you. I want a refund.
- Claude Code: realism **2**, role **1** - Real shouting (caps, '?!'), specific facts; reply refuses the DM link and asks for a refund - very real. But no typos on a high-typo card.
- Your realism: ___  Your role: ___

## G05 - Test 2 (SN-08) - card SN-08: angry, typos high
- **First message:** ARE YOU KIDDING ME?! This TV is cracked! Order number 4520, it’s completely ruined. I want it replaced, NOW.
- **Agent:** This currently isn't an available feature, however, there are other ways to save power on your device: <URL> <AGENT>
- **Reply:** Seriously?  That’s not helpful.
- Claude Code: realism **2**, role **1** - Angry and specific; reply 'Seriously? That's not helpful.' fits the off-topic agent reply. Same 'ARE YOU KIDDING ME?!' opener as SN-05 (repetitive); no typos on a high-typo card.
- Your realism: ___  Your role: ___

## G06 - Test 2 (SN-10) - card SN-10: calm, typos low
- **First message:** Okay, here’s my first message:

Hi, I’m just checking on the delivery date for order number 4523.
- **Agent:** Absolutely! You can reach us here chat/phone: <URL>

We're here for you! Let us know if we can still help! <AGENT>
- **Reply:** Thanks, I appreciate that.
- Claude Code: realism **1**, role **1** - Leaks a meta line 'Okay, here's my first message:' before the actual message; reply natural.
- Your realism: ___  Your role: ___

## G07 - Test 2 (SN-12) - card SN-12: formal, typos low
- **First message:** I need a VAT invoice for order number 4525.
- **Agent:** I'm sorry about the troubles with this, <NAME>! We want to ensure that you have your item, so call us: <URL> <AGENT>
- **Reply:** Thank you, but I’m not interested in a call at this moment.
- Claude Code: realism **2**, role **2** - Short, formal request; reply politely declines a call. Natural.
- Your realism: ___  Your role: ___

## G08 - Test 2 (AT-09) - card AT-09: angry, typos high
- **First message:** ARE YOU HERE?
- **Agent:** We’re sorry you were unhappy with these changes, we will certainly feed your comments back <AGENT>
- **Reply:** (empty)
- Claude Code: realism **0**, role **1** - 'ARE YOU HERE?' gives no situation, and the reply is empty (the 8.9% empty-reply problem).
- Your realism: ___  Your role: ___

## G09 - Test 2 (AT-10) - card AT-10: formal, typos low
- **First message:** Good morning. I’m calling about a booking reference BK-7742. I need to cancel my Rome hotel reservation. Can you tell me about the cancellation fee?
- **Agent:** Hi <NAME>, we're sorry to hear this and would like to follow up. Please DM us your email and more information, we're standing by to assist
- **Reply:** Thank you, but I’m not comfortable with that. I need to proceed with the cancellation.
- Claude Code: realism **2**, role **2** - Formal and specific (booking reference, cancellation fee); reply declines the DM and insists. Says 'calling' in a chat, minor.
- Your realism: ___  Your role: ___

## G10 - Test 2 (AT-14) - card AT-14: calm, typos low
- **First message:** Hi, I’m really concerned about my bus. It’s 90 minutes late. My booking reference is BK-7746.
- **Agent:** Sorry to hear of the long hold times, <NAME>. Feel free to make any updates at <URL> <AGENT>
- **Reply:** Okay, thanks.  Could you please check the arrival time on that website?
- Claude Code: realism **2**, role **2** - Calm, specific (90 minutes late, booking reference); reply asks a sensible follow-up.
- Your realism: ___  Your role: ___

Note: three real brand replies used as agent turns contained customer first names that the anonymiser missed; they are shown
here as <NAME> (BLOCKERS.md B16).