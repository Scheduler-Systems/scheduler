package com.schedulersystems.scheduler.ui.screens.policies

import android.content.Intent
import android.net.Uri
import androidx.compose.foundation.layout.*
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

// Legal documents: Privacy Policy + Terms & Conditions open the external Legal Center in
// the browser (parity with Flutter's policies page). Reached from Home.
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun PoliciesScreen(onNavigateBack: () -> Unit) {
    val context = LocalContext.current
    val openLegalCenter: () -> Unit = {
        runCatching {
            context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(LegalDocuments.LEGAL_CENTER_URL)))
        }
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Policies", fontSize = 22.sp, fontWeight = FontWeight.Medium, color = Color.White) },
                navigationIcon = {
                    IconButton(onClick = onNavigateBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Back", tint = Color.White)
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(containerColor = Color(0xFF6A0DAD))
            )
        }
    ) { padding ->
        Column(
            modifier = Modifier.fillMaxSize().padding(padding).padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp)
        ) {
            Button(
                onClick = openLegalCenter,
                modifier = Modifier.fillMaxWidth().height(50.dp),
                colors = ButtonDefaults.buttonColors(containerColor = Color(0xFF6A0DAD)),
                shape = MaterialTheme.shapes.small
            ) { Text("Privacy Policy", fontSize = 16.sp) }

            Button(
                onClick = openLegalCenter,
                modifier = Modifier.fillMaxWidth().height(50.dp),
                colors = ButtonDefaults.buttonColors(containerColor = Color(0xFF6A0DAD)),
                shape = MaterialTheme.shapes.small
            ) { Text("Terms & Conditions", fontSize = 16.sp) }

            Text(
                "Click on Privacy Policy or Terms & Conditions above to view the legal documents. They will open in your default browser.",
                fontSize = 14.sp,
                color = Color.Gray
            )
        }
    }
}
