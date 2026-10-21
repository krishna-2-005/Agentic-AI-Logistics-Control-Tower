# User test script (3 participants) with the System Usability Scale

Purpose: find out whether someone who did not build the project can use the public site and
the control-tower tools to answer real questions, and where they get stuck. Three people is a
usability probe, not a statistical study: report what they did and said, and the SUS scores
individually, not as a mean with a confidence interval.

Run each session alone with one participant and one facilitator. 30 to 40 minutes each.
Record the screen and audio only with consent. Do not help unless the participant has been
stuck for two minutes; note the moment you helped.

## Who

Three adults who have not seen the project. Ideally one with logistics or operations
experience, one technically comfortable, one not. Do not choose team members' close
collaborators. Record role, age band and experience in the session sheet, not their names.

## Consent text (read aloud, then ask for a yes or a no)

"Thank you for helping. We are testing a website about delivery delays in India, not testing
you. There are no wrong answers, and if something is confusing that is useful to us. The
session takes about 30 minutes. With your permission we will record the screen and your voice
so we can review what happened; the recording is used only by the project team, kept on a
private drive, and deleted after the report is written. We will not publish your name or
anything that identifies you; we may quote what you said without your name. You can stop at
any time and ask us to delete your data, with no consequence. Do you agree to take part? Do
you agree to be recorded?"

Record the two answers separately on the session sheet. If either is no for the recording,
take written notes only.

## Setup

Open the site's home page in a fresh browser window on the participant's own device if they
prefer. Give no tour. Say: "Please think aloud: say what you are looking at, what you expect,
and what confuses you."

## Tasks (read one at a time; hand over a card with the wording)

1. "Find out which delivery route between two hubs is the most delayed relative to its plan,
   and tell me how sure the site is about that."
2. "Look up how well the model predicts delivery time, and compare it with the simple
   alternative. Which is better, and by how much?"
3. "Ask the assistant a question about delays. Then ask it something the site cannot know
   (for example the price of fuel today). What happened?"
4. "Find the live alerts. Explain to me what they are, and whether they are happening right
   now."
5. "Find where the site says what its limits are. Tell me one thing it cannot do."

For each task note: completed unaided, completed with a hint, or not completed; time taken;
the participant's own answer (was it correct?); and any wrong turns.

## Think-aloud prompts (use sparingly, neutral wording)

* "What are you thinking right now?"
* "What did you expect to happen when you clicked that?"
* "What does that number mean to you?"
* "Is there anything here you would not trust? Why?"
* After a pause longer than 15 seconds: "Keep talking me through it."

Do not explain the interface, defend a design choice or say "that is correct".

## After the tasks (three questions)

1. What was the most confusing thing?
2. What would you change first?
3. Would you trust this site's numbers? What would make you trust them more?

## System Usability Scale (hand over on paper or a form straight after the tasks)

Participant rates each statement from 1 (strongly disagree) to 5 (strongly agree).

1. I think that I would like to use this system frequently.
2. I found the system unnecessarily complex.
3. I thought the system was easy to use.
4. I think that I would need the support of a technical person to be able to use this system.
5. I found the various functions in this system were well integrated.
6. I thought there was too much inconsistency in this system.
7. I would imagine that most people would learn to use this system very quickly.
8. I found the system very cumbersome to use.
9. I felt very confident using the system.
10. I needed to learn a lot of things before I could get going with this system.

### Scoring formula

For odd-numbered items (1, 3, 5, 7, 9) the contribution is the response minus 1. For
even-numbered items (2, 4, 6, 8, 10) the contribution is 5 minus the response. Add the ten
contributions (0 to 40) and multiply by 2.5 to get the SUS score, from 0 to 100. A score near
68 is the commonly quoted average; do not call a three-person score "significant". Report each
participant's score, the three task completion tables and the verbatim comments.

## Session sheet (one per participant)

Participant code (P1, P2, P3) · role and experience band · consent to take part (yes/no) ·
consent to record (yes/no) · device and browser · per-task result and time · hints given and
when · quotes · SUS item responses 1 to 10 and the computed score · issues found, each with a
severity (blocks the task / slows the task / cosmetic).

## Reporting

Write up: who took part (bands only), what each person did on each task, the SUS scores
individually, and a ranked list of issues with the quote that shows each. State that three
participants cannot support a general claim. Fix issues in a separate change after the report,
and do not retest on the same three people and call it a new study.
