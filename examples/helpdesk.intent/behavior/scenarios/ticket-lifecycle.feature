Feature: Ticket lifecycle end to end
  Scenario: Create, converse, close, archive
    Given a user and a matching analyst
    When the user creates a hardware ticket
    Then it is assigned to a hardware analyst and status is OPEN
    When the analyst replies
    Then status is IN_PROGRESS
    When the user and analyst exchange three more messages with one attachment
    Then the thread shows all messages in order and the attachment downloads with a matching sha256
    When the user closes the ticket
    Then status is CLOSED with closed_by recorded
    When 24 hours pass and the archive job runs
    Then status is ARCHIVED and the ticket appears in the admin archived report

  Scenario: Specialty routing under load
    Given two hardware analysts, one already holding two open tickets and one holding none
    When a new hardware ticket is created
    Then it is assigned to the analyst holding none (least-loaded)

  Scenario: No matching specialty
    Given no analyst has the 'access' specialty
    When a user creates an 'access' ticket
    Then it is assigned to the least-loaded analyst overall and flagged unrouted
