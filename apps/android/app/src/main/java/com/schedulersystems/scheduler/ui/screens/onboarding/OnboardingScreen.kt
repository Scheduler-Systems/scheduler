package com.schedulersystems.scheduler.ui.screens.onboarding

import android.content.Context
import androidx.compose.animation.animateColorAsState
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.pager.HorizontalPager
import androidx.compose.foundation.pager.rememberPagerState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.navigation.NavController
import com.schedulersystems.scheduler.R
import com.schedulersystems.scheduler.ui.components.SchedulerButton
import com.schedulersystems.scheduler.ui.theme.PaginationInactive
import com.schedulersystems.scheduler.ui.theme.SchedulerPrimary

private data class OnboardingSlide(
    val title: String,
    val subtitle: String,
    val imageLight: Int,
    val imageDark: Int
)

private val slides = listOf(
    OnboardingSlide(
        title = "Stay Connected",
        subtitle = "Stay connected with your team and manage schedules seamlessly from anywhere.",
        imageLight = R.drawable.stay_connected_light,
        imageDark = R.drawable.stay_connected_dark
    ),
    OnboardingSlide(
        title = "Customize Your Workflow",
        subtitle = "Tailor your scheduling workflow to fit your team's unique needs and preferences.",
        imageLight = R.drawable.customizable_approach_light,
        imageDark = R.drawable.customizable_approach_dark
    ),
    OnboardingSlide(
        title = "Algorithmic Calculation",
        subtitle = "Let our intelligent algorithm build optimal schedules while respecting everyone's availability.",
        imageLight = R.drawable.algorithmic_calculation_light,
        imageDark = R.drawable.algorithmic_calculation_dark
    )
)

@OptIn(ExperimentalFoundationApi::class)
@Composable
fun OnboardingScreen(navController: NavController) {
    val context = LocalContext.current
    val pagerState = rememberPagerState(pageCount = { slides.size })
    val isDarkTheme = androidx.compose.foundation.isSystemInDarkTheme()

    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(MaterialTheme.colorScheme.background)
    ) {
        HorizontalPager(
            state = pagerState,
            modifier = Modifier
                .weight(1f)
                .fillMaxWidth()
        ) { page ->
            OnboardingPage(
                slide = slides[page],
                isDarkTheme = isDarkTheme
            )
        }

        PaginationDots(
            pageCount = slides.size,
            currentPage = pagerState.currentPage,
            modifier = Modifier
                .fillMaxWidth()
                .padding(vertical = 24.dp)
        )

        SchedulerButton(
            text = "Start Now",
            onClick = {
                context.getSharedPreferences("scheduler_prefs", Context.MODE_PRIVATE)
                    .edit()
                    .putBoolean("onboarding_completed", true)
                    .apply()
                navController.navigate("login") {
                    popUpTo("onboarding") { inclusive = true }
                }
            },
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 32.dp, vertical = 16.dp)
        )

        Spacer(modifier = Modifier.height(16.dp))
    }
}

@Composable
private fun OnboardingPage(slide: OnboardingSlide, isDarkTheme: Boolean) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(horizontal = 32.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center
    ) {
        val imageRes = if (isDarkTheme) slide.imageDark else slide.imageLight
        androidx.compose.foundation.Image(
            painter = painterResource(id = imageRes),
            contentDescription = slide.title,
            modifier = Modifier
                .fillMaxWidth()
                .height(280.dp),
            contentScale = ContentScale.Fit
        )

        Spacer(modifier = Modifier.height(48.dp))

        Text(
            text = slide.title,
            fontSize = 28.sp,
            fontWeight = FontWeight.Bold,
            color = MaterialTheme.colorScheme.onBackground,
            textAlign = TextAlign.Center
        )

        Spacer(modifier = Modifier.height(16.dp))

        Text(
            text = slide.subtitle,
            fontSize = 16.sp,
            color = MaterialTheme.colorScheme.onBackground.copy(alpha = 0.7f),
            textAlign = TextAlign.Center,
            lineHeight = 24.sp
        )
    }
}

@Composable
private fun PaginationDots(
    pageCount: Int,
    currentPage: Int,
    modifier: Modifier = Modifier
) {
    Row(
        modifier = modifier,
        horizontalArrangement = Arrangement.Center,
        verticalAlignment = Alignment.CenterVertically
    ) {
        repeat(pageCount) { index ->
            val isActive = index == currentPage
            val color by animateColorAsState(
                targetValue = if (isActive) SchedulerPrimary else PaginationInactive,
                label = "dotColor"
            )
            Box(
                modifier = Modifier
                    .padding(horizontal = 4.dp)
                    .size(if (isActive) 12.dp else 8.dp)
                    .clip(CircleShape)
                    .background(color)
            )
        }
    }
}
