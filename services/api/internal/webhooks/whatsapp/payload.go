package whatsapp

import "encoding/json"

// metaPayload is the top-level shape of a WhatsApp Business Cloud API webhook
// POST body.
//
// Reference shape:
//
//	{
//	  "object": "whatsapp_business_account",
//	  "entry": [{
//	    "id": "WABA_ID",
//	    "changes": [{
//	      "field": "messages",
//	      "value": {
//	        "messaging_product": "whatsapp",
//	        "metadata": { "display_phone_number": "...", "phone_number_id": "..." },
//	        "contacts": [{ "profile": { "name": "Jane Doe" }, "wa_id": "1555..." }],
//	        "messages": [{
//	          "from": "1555...", "id": "wamid....", "timestamp": "1700000000",
//	          "type": "text", "text": { "body": "Hello" }
//	        }]
//	      }
//	    }]
//	  }]
//	}
//
// Only the fields this report-only receiver needs are modeled; unknown fields
// are ignored by encoding/json.
type metaPayload struct {
	Object string      `json:"object"`
	Entry  []metaEntry `json:"entry"`
}

type metaEntry struct {
	ID      string       `json:"id"`
	Changes []metaChange `json:"changes"`
}

type metaChange struct {
	Field string         `json:"field"`
	Value metaChangeData `json:"value"`
}

type metaChangeData struct {
	MessagingProduct string        `json:"messaging_product"`
	Metadata         metaMetadata  `json:"metadata"`
	Contacts         []metaContact `json:"contacts"`
	Messages         []metaMessage `json:"messages"`
}

type metaMetadata struct {
	DisplayPhoneNumber string `json:"display_phone_number"`
	PhoneNumberID      string `json:"phone_number_id"`
}

type metaContact struct {
	WaID    string `json:"wa_id"`
	Profile struct {
		Name string `json:"name"`
	} `json:"profile"`
}

type metaMessage struct {
	From      string `json:"from"`
	ID        string `json:"id"`
	Timestamp string `json:"timestamp"`
	Type      string `json:"type"`
	Text      struct {
		Body string `json:"body"`
	} `json:"text"`
}

// parsePayload unmarshals a raw Meta webhook body and flattens every inbound
// message it contains into a slice of normalized InboundMessage values.
//
// It returns an error only when the JSON itself is malformed. A well-formed
// payload that carries no messages (e.g. a status-only callback) yields a nil
// slice and a nil error — the caller treats that as "nothing to ingest".
//
// receivedAt is stamped onto every returned message so persistence has a stable
// ingestion time independent of Meta's own timestamp.
func parsePayload(raw []byte, receivedAt string) ([]InboundMessage, error) {
	var p metaPayload
	if err := json.Unmarshal(raw, &p); err != nil {
		return nil, err
	}

	var out []InboundMessage
	for _, entry := range p.Entry {
		for _, change := range entry.Changes {
			v := change.Value

			// Build a wa_id -> profile name index for this change so each
			// message can be enriched with the sender's display name.
			names := make(map[string]string, len(v.Contacts))
			for _, c := range v.Contacts {
				if c.WaID != "" && c.Profile.Name != "" {
					names[c.WaID] = c.Profile.Name
				}
			}

			for _, m := range v.Messages {
				msg := InboundMessage{
					MessageID:     m.ID,
					From:          m.From,
					Timestamp:     m.Timestamp,
					Type:          m.Type,
					ProfileName:   names[m.From],
					PhoneNumberID: v.Metadata.PhoneNumberID,
					ReceivedAt:    receivedAt,
				}
				if m.Type == "text" {
					msg.Text = m.Text.Body
				}
				out = append(out, msg)
			}
		}
	}
	return out, nil
}
