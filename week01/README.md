# Week 1 - Lab 0

This is my first practical assignment for COSC726. The main aim was to make
sure my Python and Git setup works and to learn how to read an agent trace.

The example follows a support agent helping Layla with a delayed order. The
agent checks the order, reads the late-delivery policy, and asks a person for
approval before adding a credit. This is important because the credit would
change the customer's account.

## Files in this folder

- `lab0.ipynb` contains my written answers, trace audit, PEAS worksheet, and
  decision memo. I ran the notebook from top to bottom and saved the outputs.
- `COSC726_W01_hello_agent_mock.py` contains the fixed 12-step trace and my
  sense, reason, act, and observe classifications.
- `requirements.txt` shows that this week only uses the Python standard
  library, so no extra packages are needed.

I kept the original filenames because they are the names required in the lab
instructions.

## How to check my work

Run these commands from the main repository folder:

```bash
python week01/COSC726_W01_hello_agent_mock.py --self-test
python week01/COSC726_W01_hello_agent_mock.py --check
```

The first command should print `TRACE SELF-TEST PASSED`. The second command
should give a score of `12/12`.

The notebook's final check should also show that the environment, audit, PEAS
worksheet, and decision memo are complete.
