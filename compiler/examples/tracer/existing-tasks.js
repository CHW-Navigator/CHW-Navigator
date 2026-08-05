'use strict';

const unrelatedSupervisionRule = {
  name: 'existing-unrelated-supervision-task',
  icon: 'icon-supervision',
  title: 'task.existing.supervision',
  appliesTo: 'contacts',
  events: [{ id: 'existing-supervision-event', days: 7, start: 0, end: 1 }],
  actions: [{ form: 'supervision_followup' }],
};

module.exports = [unrelatedSupervisionRule];
