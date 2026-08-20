
# The Analyst Copilot

## Problem statement

Equity analysts, credit teams and auditors spend an enormous share of their working life reading annual reports to answer questions that are, in principle, already answered somewhere in the document. A single annual filing runs past a hundred pages and dozens of tables, and the numbers that matter sit inside financial statements, footnotes and management commentary — not in plain sentences. Firms want an assistant that answers these questions in seconds. But an assistant that invents a number is worse than no assistant at all, because a wrong figure flows straight into a valuation or a credit decision. You are going to build the assistant a firm could actually trust.

## Your task

Build a **question-answering system over company annual filings, delivered as a chatbot.** Given a filing and an analyst-style question, it must return a precise answer **plus the exact place in the document it came from** — or an honest “not found in this filing.”

For the kinds of questions it must handle, refer to the practice questions provided with the data.

| What your system returns         | Score |
| -------------------------------- | ----- |
| Correct answer, correct location | +1    |
| “Not found in this filing”     | 0     |
| Correct answer, wrong location   | 0     |
| Confidently wrong answer         | −1   |

A system that guesses will finish below zero. A system that always abstains finishes at exactly zero. Neither places. The marks are in knowing the difference between an answer you can prove and one you cannot.

## The data

You receive `analyst-copilot-data.zip`:

| In the zip                         | What it is                                                                                                                                                                                                                                                |
| ---------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **practice-questions.jsonl** | 136 analyst questions, each with its correct answer and the exact passage and page that prove it. This is your development and self-evaluation set — you have the answer key on purpose.                                                                 |
| **filings/**                 | The 78 real annual and quarterly reports those questions are about, one file per document, covering 32 companies across nine sectors. Downloaded from the SEC's public archive (sec.gov/edgar), where every US-listed company's filings are free forever. |

## Required output

You are building a product, not a report. Your chatbot must have:

* **An “Add filing” control** — upload a filing it has never seen, with a visible processing status. Adding one filing must complete within 10 minutes.
* **A chat box** — analyst questions asked in plain English.
* **Evidence on every answer** — the document and page it came from, shown in the reply.
* **The ability to decline** — “not found in this filing,” stated plainly, when the evidence is not there or not strong enough.

## What to submit

 **Your code** , in a Git repository with a README that lets us run the chatbot from scratch.  **Your running system** , ready for the live session.  **A one-page approach note** : what you tried, what you measured, what you kept and what you threw away — we read this as carefully as we read your score.
