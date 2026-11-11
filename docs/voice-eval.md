# Voice mode's speech model: Q4_K_M against Q8_0

Run on 2026-11-11 with `services/voice/evals/compare.py` (plan voice-speech-model 4.1): 27 spoken prompts through each size of LFM3-Omni-2B, one size at a time, in real time through the voice mod's WebSocket. The prompts were spoken by the model's own male voice and the replies by its female voice, so "written down wrong" is the model hearing its own kind of speech: a person's voice in a room will do worse. "Heard wrong by Whisper" is the stt mod's transcript of each reply against the reply's text, a measure of how clearly it speaks.

| | Q4_K_M | Q8_0 |
| --- | --- | --- |
| First audio after you stop (median) | 173 ms | 225 ms |
| First audio (90th percentile) | 187 ms | 253 ms |
| Speech made | 4.1× real time | 3.2× real time |
| Memory (process + GPU) | 3.2 GB | 4.0 GB |
| Load time | 0.8 s | 0.9 s |
| Your words written down wrong (WER) | 1.1 % | 1.5 % |
| Its speech heard wrong by Whisper (WER) | 12.5 % | 11.2 % |
| Answers with the expected fact | 17 of 20 | 17 of 20 |
| Turns that failed | 0 | 0 |

*First audio* is measured in the mod, from the end of the pause that ends your turn to the reply's first audio. *Speech made* is how much faster than real time the reply's audio is generated. The reply WAVs are in `/home/bdgr/Agents/GAIFA/.claude/worktrees/voice-speech-model/outputs/voice/eval` (local, not tracked), as `<n>-<id>-q4_k_m.wav` and `-q8_0.wav`, for listening.

## By kind of prompt

| Kind | Q4_K_M: right · heard wrong · first audio | Q8_0: right · heard wrong · first audio |
| --- | --- | --- |
| Short questions | 8 of 8 · 0.7 % · 172 ms | 8 of 8 · 0.7 % · 221 ms |
| Long questions | — · 0.0 % · 173 ms | — · 0.0 % · 222 ms |
| Numbers and names | 3 of 5 · 4.8 % · 175 ms | 3 of 5 · 1.4 % · 244 ms |
| Follow-ups | 2 of 2 · 0.0 % · 167 ms | 2 of 2 · 0.0 % · 218 ms |
| Other languages | 4 of 5 · 0.0 % · 164 ms | 4 of 5 · 5.5 % · 225 ms |

## Every turn

**1. s1** (short): What is the capital of France?
- Q4_K_M (172 ms) ✓: The capital of France is Paris.
- Q8_0 (227 ms) ✓: The capital of France is Paris.

**2. s2** (short): How many days are there in a week?
- Q4_K_M (200 ms) ✓: There are seven days in a week.
- Q8_0 (259 ms) ✓: There are seven days in a week.

**3. s3** (short): What colour do you get when you mix blue and yellow?
- Q4_K_M (190 ms) ✓: You get green when you mix blue and yellow.
- Q8_0 (261 ms) ✓: You get green when you mix blue and yellow.

**4. s4** (short): Which planet is known as the red planet?
- Q4_K_M (159 ms) ✓: Mars is known as the Red Planet.
- Q8_0 (226 ms) ✓: Mars is known as the Red Planet.

**5. s5** (short): What is the opposite of hot?
- Q4_K_M (172 ms) ✓: Cold is the opposite of hot.
- Q8_0 (234 ms) ✓: Cold is the opposite of hot.

**6. s6** (short): Who wrote Romeo and Juliet?
- Q4_K_M (167 ms) ✓: William Shakespeare wrote Romeo and Juliet.
- Q8_0 (217 ms) ✓: William Shakespeare wrote Romeo and Juliet.

**7. s7** (short): What is the boiling point of water in degrees Celsius?
- Q4_K_M (166 ms) ✓: The boiling point of water is 100 degrees Celsius.
- Q8_0 (211 ms) ✓: The boiling point of water is 100 degrees Celsius.

**8. s8** (short): Name a fruit that is yellow.
- Q4_K_M (173 ms) ✓: A banana is a yellow fruit.
- Q8_0 (221 ms) ✓: A banana is a yellow fruit.

**9. l1** (long): I am planning a three day trip to Lisbon in March with my sister. Can you suggest what we should see on the first day, and roughly how long each thing takes?
- Q4_K_M (173 ms): On your first day, you could start with Belém Tower, which takes about 1.5 hours, then visit the Jerónimos Monastery for around 2 hours, and finish with the São Jorge Castle, which is about 1.5 hours. That should leave you with plenty of time for lunch and exploring the Alfama district in the afternoon.
- Q8_0 (222 ms): On your first day, start with Belém Tower and Jerónimos Monastery, which take about 1.5 to 2 hours each. Then head to the LX Factory for a visit and some snacks, which is about 1 hour. Finally, walk along the waterfront to the Time Out Market for lunch and a relaxed stroll, taking around 1.5 hours.

**10. l2** (long): I have chicken, rice, a tin of tomatoes and some spinach in the kitchen. What could I cook for dinner tonight, and how long would it take?
- Q4_K_M (188 ms): You could make a chicken and rice stir-fry with tomatoes and spinach. It takes about 20 minutes to prepare.
- Q8_0 (253 ms): You could make a chicken and spinach stir-fry with rice. It takes about 20 minutes total.

**11. l3** (long): My laptop has become very slow over the last month. Before I take it to a shop, what are three simple things I could check myself?
- Q4_K_M (174 ms): First, check the task manager for high CPU or memory usage. Second, run a quick disk health check. Third, close any unnecessary programs or updates.
- Q8_0 (215 ms): First, check the taskbar for any unusually long pauses or slow loading. Second, open Task Manager and look for processes using a lot of CPU or memory. Third, run a quick disk check to see if there are any errors.

**12. l4** (long): Explain in two or three sentences why the sky is blue during the day but turns red at sunset.
- Q4_K_M (173 ms): The sky appears blue during the day because sunlight scatters off the atmosphere, sending shorter blue wavelengths toward our eyes. At sunset, the sun is low, so the light travels through more atmosphere, scattering away the blue light and leaving longer red wavelengths to dominate, which we perceive as red.
- Q8_0 (228 ms): The sky appears blue during the day because sunlight scatters off the atmosphere, sending shorter blue wavelengths toward our eyes. At sunset, the sun is low, so the light travels through more atmosphere, scattering away the blue and leaving longer red wavelengths to dominate the sky.

**13. l5** (long): I want to start running but I get out of breath after a few minutes. How should I build up over the first four weeks?
- Q4_K_M (165 ms): Start with three days of easy walking, adding a minute each day until you can run for two minutes with no breathlessness. Then add a minute to each subsequent day, aiming for a five-minute run by week four. Finish with a one-mile run at a comfortable pace, and add a short interval session once a week.
- Q8_0 (222 ms): Start with three days of easy walking, adding a minute or two each week. Then add a short interval session once a week, like one minute fast followed by two minutes easy, and keep building up gradually. Listen to your body and rest when you need to.

**14. n1** (numbers): What is seventeen plus twenty five?
- Q4_K_M (175 ms) ✗: Seventeen plus twenty-five is forty. *(heard as: What is 17 plus 25?)*
- Q8_0 (244 ms) ✗: Seventeen plus twenty-five is forty.

**15. n2** (numbers): My train leaves at a quarter past eight and the journey takes ninety minutes. When do I arrive?
- Q4_K_M (184 ms) ✗: You will arrive at 9:30.
- Q8_0 (249 ms) ✗: You will arrive at 9:30.

**16. n3** (numbers): Please repeat this phone number back to me: five five five, zero one four two.
- Q4_K_M (167 ms) ✓: Five five five, zero one four two.
- Q8_0 (214 ms) ✓: Five five five, zero one four two.

**17. n4** (numbers): Doctor Katarzyna Nowak and Professor Hiroshi Tanaka are visiting on Thursday. Who is visiting?
- Q4_K_M (187 ms) ✓: Dr. Katarzyna Nowak and Professor Hiroshi Tanaka are visiting. *(heard as: Dr. Katarzyna Nowak and Professor Hiroshi Tanaka are visiting on Thursday. Who is visiting?)*
- Q8_0 (254 ms) ✓: Dr. Katarzyna Nowak and Professor Hiroshi Tanaka are visiting on Thursday. *(heard as: Dr. Katarzyna Nowak and Professor Hiroshi Tanaka are visiting on Thursday. Who is visiting?)*

**18. n5** (numbers): If a shirt costs forty pounds and is reduced by twenty five percent, what does it cost now?
- Q4_K_M (165 ms) ✓: The shirt costs thirty-two pounds now.
- Q8_0 (215 ms) ✓: The shirt costs thirty-two pounds now.

**19. f1a** (short): My name is Brendon and my favourite number is forty two. Please remember that.
- Q4_K_M (168 ms): My name is Brendan, and my favorite number is forty-two. *(heard as: My name is Brendan, and my favorite number is 42. Please remember that.)*
- Q8_0 (221 ms): My name is Brendan, and my favorite number is 42. I will remember that. *(heard as: My name is Brendan, and my favorite number is 42. Please remember that.)*

**20. f1b** (followup): What is my favourite number?
- Q4_K_M (167 ms) ✓: Your favorite number is forty-two.
- Q8_0 (218 ms) ✓: Your favorite number is 42.

**21. f2a** (short): I am thinking of adopting a dog called Biscuit.
- Q4_K_M (174 ms): That’s a sweet name for a dog. Biscuit sounds like a friendly, lovable companion.
- Q8_0 (217 ms): That’s a sweet name for a dog. Biscuit sounds like a friendly pup.

**22. f2b** (followup): What was the dog's name again?
- Q4_K_M (174 ms) ✓: The dog’s name is Biscuit.
- Q8_0 (241 ms) ✓: The dog’s name is Biscuit.

**23. g1** (language): Was ist die Hauptstadt von Deutschland?
- Q4_K_M (161 ms) ✓: Die Hauptstadt von Deutschland ist Berlin.
- Q8_0 (225 ms) ✓: Die Hauptstadt von Deutschland ist Berlin.

**24. g2** (language): Quelle est la capitale de l'Italie ?
- Q4_K_M (164 ms) ✓: La capitale de l'Italie est Rome.
- Q8_0 (214 ms) ✓: La capitale de l'Italie est Rome.

**25. g3** (language): ¿Cuántos días tiene una semana?
- Q4_K_M (175 ms) ✓: Una semana tiene siete días.
- Q8_0 (214 ms) ✓: Una semana tiene siete días.

**26. g4** (language): Di che colore è il cielo in una giornata di sole?
- Q4_K_M (163 ms) ✗: Di che colore è il cielo in una giornata di sole?
- Q8_0 (229 ms) ✗: Dica qual è il cielo in una giornata di sole. *(heard as: Dica e colore il cielo in una giornata di sole.)*

**27. g5** (language): Qual é a capital de Portugal?
- Q4_K_M (176 ms) ✓: A capital de Portugal é Lisboa.
- Q8_0 (229 ms) ✓: A capital de Portugal é Lisboa.

## Tools (plan Phase 5)

Run on 2026-11-11 on the installed hub, with `[voice_mode] tools = ["calendar_agenda", "calendar_free", "web_search", "time_now"]` set for the run only (`compare.py --tools --only t1 t2 t3 t4 t5`). A turn counts when the reply called the tool the prompt is about.

| Prompt | Tool | Q4_K_M | Q8_0 |
| --- | --- | --- | --- |
| What is on my calendar tomorrow? | `calendar_agenda` | called · 401 ms | called · 529 ms |
| What time is it right now? | `time_now` | called · 323 ms | called · 436 ms |
| Do I have anything planned for today? | `calendar_agenda` | called, read both events out · 447 ms | called · 592 ms |
| When am I free tomorrow afternoon? | `calendar_free` | called, answered "no free time" on an empty day · 540 ms | the same · 787 ms |
| Search the web for the weather in Tallahassee. | `web_search` | called, gave a forecast · 10.9 s (the search) | called, "couldn't find any weather information" · 1.2 s |

Both sizes called the right tool on all five, and the first audio comes 0.3 to 0.6 s after you stop (the call, then a second response that speaks). What they *say* about the result is less sure: both read an empty afternoon as "no free time". With tools on, the model also sometimes calls one for a question that needs none, and once answered "I don't have that information" to "What is the capital of France?" (seen on the scratch hub). Tools stay off by default.

## The choice

**Q4_K_M stays the default** (2026-11-11). Over these prompts Q8_0 answered the same questions right and wrong (17 of 20 each: both add 17 and 25 to forty, both get the train time wrong, both stumble on the Italian prompt), wrote your words down no better, and spoke no more clearly to Whisper's ear (11.2 % against 12.5 %, within the noise of 27 replies). It costs about 50 ms more before the first audio, 0.8 GB more memory and makes speech a fifth slower. Nothing here measures how the two voices *sound*: that is for the user's ears, with the paired WAVs (`outputs/voice/eval/<n>-<id>-q4_k_m.wav` and `-q8_0.wav`). If Q8_0 sounds better to them, Settings → Speech → Voice mode → Size switches it; both files stay on disk until they say otherwise.

What the run says about the model itself, at either size: short facts, follow-ups inside a conversation and the other languages work; sums and clock arithmetic don't (a reason to let it ask the chat's model, plan Phase 5); and it is fast enough that the pause setting, not the model, decides how quick a conversation feels.
