# Week 5 - MCP and HL7 FHIR Project Proposal

My course project is an MCP-based ambulance handoff gateway using HL7 FHIR. It
converts synthetic prehospital records into validated FHIR resources and helps
prepare a safe, auditable handoff for the receiving emergency department.
The dataset combines Synthea FHIR R4 patients, NEMSIS field definitions, and
manually generated synthetic ambulance events.

- `project_proposal.md` - editable Markdown proposal
- `project_proposal.tex` - formatted LaTeX proposal source
- `output/pdf/project_proposal.pdf` - submission-ready PDF proposal
- `proposal_checklist.md` - short completion and acceptance checklist

This week is a proposal assignment, so implementation code is scheduled for
later project milestones. The planned demo will run in Google Colab, use only
synthetic patients, and will not diagnose, recommend treatment, or dispatch an
ambulance.
