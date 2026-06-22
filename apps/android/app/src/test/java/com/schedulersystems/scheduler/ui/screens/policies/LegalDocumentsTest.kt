package com.schedulersystems.scheduler.ui.screens.policies

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

// Privacy Policy + Terms & Conditions both open the external Legal Center (parity with
// Flutter's LegalDocumentsHelper). The policies screen drives this URL.
class LegalDocumentsTest {

    @Test
    fun `legal center url is the scheduler-systems legal page`() {
        assertEquals("https://scheduler-systems.com/legal", LegalDocuments.LEGAL_CENTER_URL)
        assertTrue(LegalDocuments.LEGAL_CENTER_URL.startsWith("https://"))
    }
}
