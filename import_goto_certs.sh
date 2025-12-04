#!/bin/bash

# Import GoTo/ZScaler certificates into all Java keystores

CERT_FOLDER="$1"

if [[ -z "$CERT_FOLDER" ]]; then
    echo "Usage: $0 <folder_path>"
    exit 1
fi

if [[ ! -d "$CERT_FOLDER" ]]; then
    echo "Error: '$CERT_FOLDER' is not a valid directory"
    exit 1
fi

# Common JVM installation locations on macOS
JVM_LOCATIONS=(
    "/Library/Java/JavaVirtualMachines"
    "$HOME/Library/Java/JavaVirtualMachines"
    "/opt/homebrew/opt/openjdk*/libexec"
    "/opt/homebrew/Cellar/openjdk*/*/libexec"
    "/usr/local/opt/openjdk*/libexec"
    "/usr/local/Cellar/openjdk*/*/libexec"
    "$HOME/.sdkman/candidates/java"
    "$HOME/.jdks"
    "$HOME/.asdf/installs/java"
    "$HOME/Applications/IntelliJ IDEA*.app/Contents/jbr"
    "/Applications/IntelliJ IDEA*.app/Contents/jbr"
    "$HOME/Applications/Android Studio*.app/Contents/jbr"
    "/Applications/Android Studio*.app/Contents/jbr"
)

# Check for certificates
ROOT_CERT="$CERT_FOLDER/GoToRootCA1.pem"
INTERMEDIATE_CERT="$CERT_FOLDER/AVX_GoTo_Intermediate_CA_01.pem"

FOUND_ROOT=false
FOUND_INTERMEDIATE=false

if [[ -f "$ROOT_CERT" ]]; then
    FOUND_ROOT=true
    echo "Found: GoToRootCA1.pem"
fi

if [[ -f "$INTERMEDIATE_CERT" ]]; then
    FOUND_INTERMEDIATE=true
    echo "Found: AVX_GoTo_Intermediate_CA_01.pem"
fi

if [[ "$FOUND_ROOT" == false && "$FOUND_INTERMEDIATE" == false ]]; then
    echo "No certificates found in '$CERT_FOLDER'. Exiting."
    exit 0
fi

# Find all Java installations
find_java_homes() {
    local found=()
    
    for pattern in "${JVM_LOCATIONS[@]}"; do
        # Expand globs and check each location
        for location in $pattern; do
            [[ ! -d "$location" ]] && continue
            
            # Standard macOS JVM structure
            for jvm in "$location"/*/Contents/Home; do
                if [[ -d "$jvm" && -x "$jvm/bin/keytool" ]]; then
                    found+=("$jvm")
                fi
            done
            
            # Direct Home directory (Homebrew, SDKMAN, asdf, .jdks)
            if [[ -x "$location/bin/keytool" ]]; then
                found+=("$location")
            fi
            
            # Subdirectories with bin/keytool (SDKMAN, asdf, .jdks style)
            for jvm in "$location"/*/; do
                if [[ -d "$jvm" && -x "$jvm/bin/keytool" ]]; then
                    found+=("$jvm")
                fi
            done
        done
    done
    
    # Remove duplicates and print
    printf '%s\n' "${found[@]}" | sort -u
}

# Collect and display JVMs
echo ""
echo "Searching for Java installations..."
JVMS=()
while IFS= read -r line; do
    [[ -n "$line" ]] && JVMS+=("$line")
done < <(find_java_homes)

if [[ ${#JVMS[@]} -eq 0 ]]; then
    echo "No valid Java installations found."
    exit 1
fi

echo ""
echo "Found Java installations:"
for JAVA_HOME in "${JVMS[@]}"; do
    echo "  - $JAVA_HOME"
done

echo ""
echo "Importing certificates..."

for JAVA_HOME in "${JVMS[@]}"; do
    KEYTOOL="$JAVA_HOME/bin/keytool"
    echo ""
    echo "Processing: $JAVA_HOME"

    if [[ "$FOUND_ROOT" == true ]]; then
        OUTPUT=$("$KEYTOOL" -importcert -cacerts -alias "GoTo-ZScaler" -file "$ROOT_CERT" -noprompt -storepass changeit 2>&1)
        if echo "$OUTPUT" | grep -q "already exists"; then
            echo "  GoTo-ZScaler: ALREADY INSTALLED"
        elif echo "$OUTPUT" | grep -q "Certificate was added to keystore"; then
            echo "  GoTo-ZScaler: INSTALLED"
        else
            echo "  GoTo-ZScaler: FAILED - $OUTPUT"
        fi
    fi

    if [[ "$FOUND_INTERMEDIATE" == true ]]; then
        OUTPUT=$("$KEYTOOL" -importcert -cacerts -alias "GoToZScaler-AVX" -file "$INTERMEDIATE_CERT" -noprompt -storepass changeit 2>&1)
        if echo "$OUTPUT" | grep -q "already exists"; then
            echo "  GoToZScaler-AVX: ALREADY INSTALLED"
        elif echo "$OUTPUT" | grep -q "Certificate was added to keystore"; then
            echo "  GoToZScaler-AVX: INSTALLED"
        else
            echo "  GoToZScaler-AVX: FAILED - $OUTPUT"
        fi
    fi
done

echo ""
echo "Certificate import complete."
