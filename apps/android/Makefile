# Scheduler — Android app (Kotlin/Compose). Build, test, and run on an emulator.
#
# JDK resolution (Android Gradle needs JDK 17+): use $JAVA_HOME if set, else
# Android Studio's bundled JBR, else /usr/libexec/java_home. This lets `make`
# work out-of-the-box even when no `java` is on PATH.
JAVA_HOME ?= $(shell \
  if [ -n "$$JAVA_HOME" ]; then echo "$$JAVA_HOME"; \
  elif [ -d "/Applications/Android Studio.app/Contents/jbr/Contents/Home" ]; then echo "/Applications/Android Studio.app/Contents/jbr/Contents/Home"; \
  else /usr/libexec/java_home 2>/dev/null; fi)
export JAVA_HOME

ANDROID_HOME ?= $(HOME)/Library/Android/sdk
ADB      := $(ANDROID_HOME)/platform-tools/adb
EMULATOR := $(ANDROID_HOME)/emulator/emulator
AVD      ?= Medium_Phone_API_34
APK      := app/build/outputs/apk/debug/app-debug.apk
PKG      := com.schedulersystems.scheduler

.PHONY: help build test lint clean emulator install run dev uninstall logcat

help: ## List available targets
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'

build: ## Build the debug APK
	./gradlew assembleDebug

test: ## Run unit tests
	./gradlew test

lint: ## Run Android lint
	./gradlew lintDebug

clean: ## Remove build outputs
	./gradlew clean

emulator: ## Boot $(AVD) if no device/emulator is attached
	@if ! $(ADB) get-state >/dev/null 2>&1; then \
	  echo "Booting emulator $(AVD)..."; \
	  $(EMULATOR) -avd $(AVD) -no-snapshot -no-boot-anim >/dev/null 2>&1 & \
	  $(ADB) wait-for-device; \
	  $(ADB) shell 'while [ "$$(getprop sys.boot_completed)" != "1" ]; do sleep 2; done'; \
	  echo "Emulator ready."; \
	else echo "Device already attached."; fi

install: build ## Build + install the debug APK on the attached device
	$(ADB) install -r $(APK)

run: emulator install ## Build, ensure an emulator, install, and launch the app
	$(ADB) shell am start -n $(PKG)/.MainActivity

dev: run ## Alias for `run` (build + launch on an emulator)

uninstall: ## Remove the app from the device
	-$(ADB) uninstall $(PKG)

logcat: ## Tail the app's logs
	$(ADB) logcat --pid=$$($(ADB) shell pidof -s $(PKG))
