"""Free-text -> questionnaire Answers.

Deliberately a separate package from app.assessment: that package is tested
to import nothing from OpenAI, and this one exists to make the one paid call.
The engine never sees prose; it sees Answers the user has confirmed.
"""
