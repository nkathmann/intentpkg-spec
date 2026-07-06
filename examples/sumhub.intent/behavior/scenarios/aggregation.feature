Feature: Multi-source aggregation
  Scenario: Three producers, one consumer
    Given a fresh store
    When sysA posts 10 and sysB posts 20 and sysC posts 12
    Then GET /api/sum returns sum 42 and count 3

  Scenario: Concurrent posts all count
    When 10 producers post value 1 concurrently
    Then GET /api/sum increases by exactly 10
