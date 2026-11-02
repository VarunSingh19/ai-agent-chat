/**
 * English UI copy for <pdk-assistant> (Architecture.md §4, Design.md §8: strings only here).
 * Sentence case, plain words, no codes or provider text (Design.md §1, §6.1 error-row).
 */
export const EN_STRINGS = {
  launcherLabel: 'Chat with building assistant',
  launcherBadgeLabel: 'New reply from staff',
  panelTitle: 'Building assistant',
  statusAssistant: 'Assistant',
  statusStaff: 'Staff',
  closeLabel: 'Close chat',

  logLabel: 'Conversation',
  youLabel: 'You',
  assistantLabel: 'Assistant',
  staffLabel: 'Staff',
  sentAt: (time: string) => `Sent at ${time}`,
  answerCutOffLabel: 'Cut off',

  emptyIntro:
    'I can check your requests, report a problem for you, and answer questions from your building’s documents.',
  starterStatus: 'Check my request status',
  starterStatusMessage: 'What is the status of my maintenance request?',
  starterReport: 'Report a problem',
  starterReportMessage: 'I want to report a maintenance problem.',
  starterRules: 'Ask about building rules',
  starterRulesMessage: 'What are the building rules I should know about?',
  talkToPerson: 'Talk to a person',

  composerLabel: 'Message',
  composerPlaceholder: 'Type your message',
  sendButton: 'Send',
  charactersLeft: (n: number) => `${n} characters left`,

  typing: 'Assistant is typing',
  toolDefault: 'Looking that up…',
  toolSentences: {
    get_request: 'Checking your requests…',
    list_requests: 'Checking your requests…',
    get_balance: 'Looking up your balance…',
    get_lease: 'Looking up your lease…',
    search_knowledge: 'Checking your building’s documents…',
    create_request: 'Preparing your request…',
    add_request_note: 'Preparing your note…',
  } as Record<string, string>,

  sourcePrefix: 'From:',
  sourceMore: (n: number) => `+${n} more`,
  noSource: 'I couldn’t find this in your building’s documents.',
  askStaff: 'Ask staff',

  slipHeadingRequest: 'Review this request',
  slipHeadingNote: 'Review this note',
  slipWhat: 'What',
  slipSend: 'Send request',
  slipSendNote: 'Send note',
  slipEdit: 'Edit',
  slipSave: 'Save changes',
  slipCancel: 'Cancel',
  slipKeep: 'Keep as is',
  slipSending: 'Sending…',
  slipSent: 'Request sent',
  slipNoteSent: 'Note sent',
  slipReference: (ref: string) => `Reference ${ref}`,
  slipExpiresIn: (min: number) => (min <= 1 ? 'Expires in 1 min' : `Expires in ${min} min`),
  slipOneMinuteLeft: 'This request expires in 1 minute.',
  slipExpired: 'This request expired. Ask me again to start a new one.',
  slipCancelled: 'Request cancelled.',
  slipReplaced: 'Replaced',
  slipFailed: 'The request didn’t go through.',
  slipEditLabel: 'Describe the request',
  editRequestMessage: (text: string) => `Please change my request to: ${text}`,
  tryAgain: 'Try again',

  handoffWaiting: 'A staff member will reply here. Usual wait: a few hours.',
  handoffTimedOut: 'Nobody is available right now. Expect a reply within one business day.',
  openRequestForm: 'Open the request form',
  handoffStaff: 'A staff member is helping you.',
  emergencyBanner:
    'If this is an emergency, call 911 now. Property emergency dispatch has been alerted.',
  emergencyCall: 'Call 911',
  emergencyNumber: '911',

  eventHandoffRequested: 'You asked for a person. A staff member will reply here.',
  eventStaffJoined: 'A staff member joined the chat.',
  eventHandedBack: 'The assistant is back in the chat.',
  eventClosed: 'This chat was closed.',
  startNewChat: 'Start a new chat',
  newStaffReply: 'New reply from staff.',

  degradedNotice:
    'I can only answer common questions right now. For anything else, use the request form or ask for staff.',

  errorRateLimited: (s: number) => `You’re sending messages quickly. Try again in ${s} seconds.`,
  errorProviderUnavailable:
    'The assistant isn’t available right now. You can use the request form or ask for staff.',
  errorReconnecting: 'Connection lost. Reconnecting…',
  errorConnectionLost: 'Connection lost.',
  errorCutOff: 'This answer was cut off.',
  errorSendFailed: 'Your message didn’t send.',
  errorUnavailable: 'The chat can’t load right now.',
} as const;

export type Strings = typeof EN_STRINGS;
