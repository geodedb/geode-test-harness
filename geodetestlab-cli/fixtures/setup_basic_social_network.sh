#!/usr/bin/env bash
# Test Fixture Setup: Basic Social Network Database
# This script creates a simple social network dataset for testing
# without relying on complex advanced types.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
GEODE_BIN="${GEODE_BIN:-$PROJECT_ROOT/zig-out/bin/geode}"
GEODE_SERVER="${GEODE_SERVER:-127.0.0.1:3141}"

echo "=== Basic Social Network Test Fixture Setup ==="
echo "Geode Binary: $GEODE_BIN"
echo "Geode Server: $GEODE_SERVER"
echo

# Check if geode binary exists
if [ ! -f "$GEODE_BIN" ]; then
    echo "ERROR: Geode binary not found at $GEODE_BIN"
    echo "Please build geode first: make build"
    exit 1
fi

# Function to execute a query
execute_query() {
    local query="$1"
    local description="$2"

    echo ">>> $description"
    if echo "$query" | "$GEODE_BIN" query --server "$GEODE_SERVER" --insecure - 2>&1 | grep -q "status_class\":\"00000"; then
        echo "    ✓ Success"
    else
        echo "    ⚠ May have failed (this might be expected)"
    fi
    echo
}

echo "Creating Locations..."
execute_query "CREATE (:Location {id: 'loc-1', name: 'San Francisco', type: 'city', population: 815201, timezone: 'America/Los_Angeles', country_code: 'US'})" "Location: San Francisco"
execute_query "CREATE (:Location {id: 'loc-2', name: 'New York', type: 'city', population: 8336817, timezone: 'America/New_York', country_code: 'US'})" "Location: New York"
execute_query "CREATE (:Location {id: 'loc-3', name: 'London', type: 'city', population: 9002488, timezone: 'Europe/London', country_code: 'GB'})" "Location: London"
execute_query "CREATE (:Location {id: 'loc-4', name: 'Tokyo', type: 'city', population: 13960000, timezone: 'Asia/Tokyo', country_code: 'JP'})" "Location: Tokyo"
execute_query "CREATE (:Location {id: 'loc-5', name: 'Berlin', type: 'city', population: 3645000, timezone: 'Europe/Berlin', country_code: 'DE'})" "Location: Berlin"

echo "Creating Companies..."
execute_query "CREATE (:Company {id: 'comp-1', name: 'TechCorp Industries', ticker: 'TECH', industry: 'Technology', employees: 50000, website: 'https://techcorp.example.com', description: 'Leading provider of enterprise software solutions'})" "Company: TechCorp"
execute_query "CREATE (:Company {id: 'comp-2', name: 'Global Finance Group', ticker: 'GFG', industry: 'Finance', employees: 75000, website: 'https://globalfinance.example.com', description: 'International investment banking'})" "Company: Global Finance"
execute_query "CREATE (:Company {id: 'comp-3', name: 'BioHealth Solutions', ticker: 'BHS', industry: 'Healthcare', employees: 12000, website: 'https://biohealth.example.com', description: 'Pharmaceutical research'})" "Company: BioHealth"

echo "Creating Users..."
execute_query "CREATE (:User {id: 'user-1', username: 'alice_tech', full_name: 'Alice Johnson', email: 'alice@techcorp.example.com', bio: 'Software engineer passionate about cloud computing', location: 'San Francisco', verified: true, follower_count: 1250, following_count: 342})" "User: Alice"
execute_query "CREATE (:User {id: 'user-2', username: 'bob_finance', full_name: 'Bob Smith', email: 'bob@globalfinance.example.com', bio: 'Senior financial analyst', location: 'New York', verified: true, follower_count: 890, following_count: 245})" "User: Bob"
execute_query "CREATE (:User {id: 'user-3', username: 'charlie_health', full_name: 'Charlie Brown', email: 'charlie@biohealth.example.com', bio: 'Medical researcher', location: 'London', verified: false, follower_count: 456, following_count: 189})" "User: Charlie"
execute_query "CREATE (:User {id: 'user-4', username: 'diana_dev', full_name: 'Diana Prince', email: 'diana@techcorp.example.com', bio: 'Full-stack developer', location: 'Berlin', verified: true, follower_count: 2100, following_count: 512})" "User: Diana"
execute_query "CREATE (:User {id: 'user-5', username: 'eve_analyst', full_name: 'Eve Anderson', email: 'eve@globalfinance.example.com', bio: 'Data scientist', location: 'Tokyo', verified: false, follower_count: 678, following_count: 234})" "User: Eve"

echo "Creating Posts..."
execute_query "CREATE (:Post {id: 'post-1', content: 'Excited to announce our new cloud platform!', likes: 125, shares: 45, comments: 23})" "Post 1"
execute_query "CREATE (:Post {id: 'post-2', content: 'Market analysis shows strong growth in tech sector', likes: 89, shares: 34, comments: 15})" "Post 2"
execute_query "CREATE (:Post {id: 'post-3', content: 'Breakthrough in medical research announced today', likes: 234, shares: 78, comments: 56})" "Post 3"
execute_query "CREATE (:Post {id: 'post-4', content: 'Tips for improving code quality', likes: 456, shares: 123, comments: 89})" "Post 4"
execute_query "CREATE (:Post {id: 'post-5', content: 'Financial markets update for Q4', likes: 67, shares: 23, comments: 12})" "Post 5"

echo "Creating Groups..."
execute_query "CREATE (:Group {id: 'group-1', name: 'Cloud Computing Enthusiasts', description: 'Discussing latest cloud technologies', member_count: 5420, privacy: 'public'})" "Group: Cloud Computing"
execute_query "CREATE (:Group {id: 'group-2', name: 'Finance Professionals', description: 'Network for finance industry professionals', member_count: 3210, privacy: 'public'})" "Group: Finance"
execute_query "CREATE (:Group {id: 'group-3', name: 'Healthcare Innovation', description: 'Medical research and innovation', member_count: 1890, privacy: 'private'})" "Group: Healthcare"

echo "Creating Topics..."
execute_query "CREATE (:Topic {id: 'topic-1', name: 'cloud-computing', category: 'Technology', trending_score: 0.85})" "Topic: cloud-computing"
execute_query "CREATE (:Topic {id: 'topic-2', name: 'finance', category: 'Business', trending_score: 0.72})" "Topic: finance"
execute_query "CREATE (:Topic {id: 'topic-3', name: 'healthcare', category: 'Medical', trending_score: 0.68})" "Topic: healthcare"
execute_query "CREATE (:Topic {id: 'topic-4', name: 'software-engineering', category: 'Technology', trending_score: 0.91})" "Topic: software-engineering"

echo
echo "Creating Relationships..."
echo

# User relationships
execute_query "MATCH (a:User {id: 'user-1'}), (b:User {id: 'user-2'}) CREATE (a)-[:FOLLOWS {since: 1640995200}]->(b)" "Alice follows Bob"
execute_query "MATCH (a:User {id: 'user-1'}), (b:User {id: 'user-4'}) CREATE (a)-[:FOLLOWS {since: 1640995200}]->(b)" "Alice follows Diana"
execute_query "MATCH (a:User {id: 'user-2'}), (b:User {id: 'user-3'}) CREATE (a)-[:FOLLOWS {since: 1640995200}]->(b)" "Bob follows Charlie"
execute_query "MATCH (a:User {id: 'user-4'}), (b:User {id: 'user-1'}) CREATE (a)-[:FOLLOWS {since: 1640995200}]->(b)" "Diana follows Alice"
execute_query "MATCH (a:User {id: 'user-5'}), (b:User {id: 'user-2'}) CREATE (a)-[:FOLLOWS {since: 1640995200}]->(b)" "Eve follows Bob"

# Friends relationships
execute_query "MATCH (a:User {id: 'user-1'}), (b:User {id: 'user-4'}) CREATE (a)-[:FRIENDS_WITH {since: 1640995200, closeness_score: 0.95}]->(b)" "Alice & Diana are friends"
execute_query "MATCH (a:User {id: 'user-2'}), (b:User {id: 'user-5'}) CREATE (a)-[:FRIENDS_WITH {since: 1640995200, closeness_score: 0.82}]->(b)" "Bob & Eve are friends"

# Post relationships
execute_query "MATCH (u:User {id: 'user-1'}), (p:Post {id: 'post-1'}) CREATE (u)-[:POSTED {timestamp: 1640995200}]->(p)" "Alice posted post-1"
execute_query "MATCH (u:User {id: 'user-2'}), (p:Post {id: 'post-2'}) CREATE (u)-[:POSTED {timestamp: 1640995200}]->(p)" "Bob posted post-2"
execute_query "MATCH (u:User {id: 'user-3'}), (p:Post {id: 'post-3'}) CREATE (u)-[:POSTED {timestamp: 1640995200}]->(p)" "Charlie posted post-3"
execute_query "MATCH (u:User {id: 'user-4'}), (p:Post {id: 'post-4'}) CREATE (u)-[:POSTED {timestamp: 1640995200}]->(p)" "Diana posted post-4"
execute_query "MATCH (u:User {id: 'user-5'}), (p:Post {id: 'post-5'}) CREATE (u)-[:POSTED {timestamp: 1640995200}]->(p)" "Eve posted post-5"

# Likes
execute_query "MATCH (u:User {id: 'user-2'}), (p:Post {id: 'post-1'}) CREATE (u)-[:LIKES {timestamp: 1640995200, reaction: 'like'}]->(p)" "Bob likes Alice's post"
execute_query "MATCH (u:User {id: 'user-3'}), (p:Post {id: 'post-1'}) CREATE (u)-[:LIKES {timestamp: 1640995200, reaction: 'love'}]->(p)" "Charlie loves Alice's post"
execute_query "MATCH (u:User {id: 'user-1'}), (p:Post {id: 'post-4'}) CREATE (u)-[:LIKES {timestamp: 1640995200, reaction: 'like'}]->(p)" "Alice likes Diana's post"

# Work relationships
execute_query "MATCH (u:User {id: 'user-1'}), (c:Company {id: 'comp-1'}) CREATE (u)-[:WORKS_AT {position: 'Senior Software Engineer', department: 'Engineering', is_current: true}]->(c)" "Alice works at TechCorp"
execute_query "MATCH (u:User {id: 'user-4'}), (c:Company {id: 'comp-1'}) CREATE (u)-[:WORKS_AT {position: 'Full Stack Developer', department: 'Engineering', is_current: true}]->(c)" "Diana works at TechCorp"
execute_query "MATCH (u:User {id: 'user-2'}), (c:Company {id: 'comp-2'}) CREATE (u)-[:WORKS_AT {position: 'Senior Analyst', department: 'Finance', is_current: true}]->(c)" "Bob works at Global Finance"
execute_query "MATCH (u:User {id: 'user-5'}), (c:Company {id: 'comp-2'}) CREATE (u)-[:WORKS_AT {position: 'Data Scientist', department: 'Analytics', is_current: true}]->(c)" "Eve works at Global Finance"
execute_query "MATCH (u:User {id: 'user-3'}), (c:Company {id: 'comp-3'}) CREATE (u)-[:WORKS_AT {position: 'Researcher', department: 'R&D', is_current: true}]->(c)" "Charlie works at BioHealth"

# Group memberships
execute_query "MATCH (u:User {id: 'user-1'}), (g:Group {id: 'group-1'}) CREATE (u)-[:MEMBER_OF {joined_at: 1640995200, role: 'admin'}]->(g)" "Alice is admin of Cloud group"
execute_query "MATCH (u:User {id: 'user-4'}), (g:Group {id: 'group-1'}) CREATE (u)-[:MEMBER_OF {joined_at: 1640995200, role: 'member'}]->(g)" "Diana is member of Cloud group"
execute_query "MATCH (u:User {id: 'user-2'}), (g:Group {id: 'group-2'}) CREATE (u)-[:MEMBER_OF {joined_at: 1640995200, role: 'admin'}]->(g)" "Bob is admin of Finance group"
execute_query "MATCH (u:User {id: 'user-5'}), (g:Group {id: 'group-2'}) CREATE (u)-[:MEMBER_OF {joined_at: 1640995200, role: 'member'}]->(g)" "Eve is member of Finance group"
execute_query "MATCH (u:User {id: 'user-3'}), (g:Group {id: 'group-3'}) CREATE (u)-[:MEMBER_OF {joined_at: 1640995200, role: 'admin'}]->(g)" "Charlie is admin of Healthcare group"

# Location relationships
execute_query "MATCH (u:User {id: 'user-1'}), (l:Location {id: 'loc-1'}) CREATE (u)-[:LOCATED_IN {is_primary: true}]->(l)" "Alice located in SF"
execute_query "MATCH (u:User {id: 'user-2'}), (l:Location {id: 'loc-2'}) CREATE (u)-[:LOCATED_IN {is_primary: true}]->(l)" "Bob located in NYC"
execute_query "MATCH (u:User {id: 'user-3'}), (l:Location {id: 'loc-3'}) CREATE (u)-[:LOCATED_IN {is_primary: true}]->(l)" "Charlie located in London"
execute_query "MATCH (u:User {id: 'user-4'}), (l:Location {id: 'loc-5'}) CREATE (u)-[:LOCATED_IN {is_primary: true}]->(l)" "Diana located in Berlin"
execute_query "MATCH (u:User {id: 'user-5'}), (l:Location {id: 'loc-4'}) CREATE (u)-[:LOCATED_IN {is_primary: true}]->(l)" "Eve located in Tokyo"

# Topic tagging
execute_query "MATCH (p:Post {id: 'post-1'}), (t:Topic {id: 'topic-1'}) CREATE (p)-[:TAGGED_WITH {confidence: 0.95}]->(t)" "Post 1 tagged cloud-computing"
execute_query "MATCH (p:Post {id: 'post-2'}), (t:Topic {id: 'topic-2'}) CREATE (p)-[:TAGGED_WITH {confidence: 0.92}]->(t)" "Post 2 tagged finance"
execute_query "MATCH (p:Post {id: 'post-3'}), (t:Topic {id: 'topic-3'}) CREATE (p)-[:TAGGED_WITH {confidence: 0.89}]->(t)" "Post 3 tagged healthcare"
execute_query "MATCH (p:Post {id: 'post-4'}), (t:Topic {id: 'topic-4'}) CREATE (p)-[:TAGGED_WITH {confidence: 0.96}]->(t)" "Post 4 tagged software-engineering"

echo
echo "=== Verifying Loaded Data ==="
echo

# Verify data was loaded
echo ">>> Checking node counts..."
NODE_COUNT=$("$GEODE_BIN" query --server "$GEODE_SERVER" --insecure "MATCH (n) RETURN count(n) AS total" 2>/dev/null | grep -o '"rows":\[\[[0-9]*\]\]' | grep -o '[0-9]*' || echo "0")
echo "    Total nodes: $NODE_COUNT"

echo ">>> Checking relationship counts..."
REL_COUNT=$("$GEODE_BIN" query --server "$GEODE_SERVER" --insecure "MATCH ()-[r]->() RETURN count(r) AS total" 2>/dev/null | grep -o '"rows":\[\[[0-9]*\]\]' | grep -o '[0-9]*' || echo "0")
echo "    Total relationships: $REL_COUNT"

echo ">>> Sample queries..."
echo -n "    Users in San Francisco: "
"$GEODE_BIN" query --server "$GEODE_SERVER" --insecure "MATCH (u:User)-[:LOCATED_IN]->(l:Location {name: 'San Francisco'}) RETURN count(u) AS total" 2>/dev/null | grep -o '"rows":\[\[[0-9]*\]\]' | grep -o '[0-9]*' || echo "0"

echo -n "    Posts by Alice: "
"$GEODE_BIN" query --server "$GEODE_SERVER" --insecure "MATCH (u:User {username: 'alice_tech'})-[:POSTED]->(p:Post) RETURN count(p) AS total" 2>/dev/null | grep -o '"rows":\[\[[0-9]*\]\]' | grep -o '[0-9]*' || echo "0"

echo -n "    TechCorp employees: "
"$GEODE_BIN" query --server "$GEODE_SERVER" --insecure "MATCH (u:User)-[:WORKS_AT]->(c:Company {name: 'TechCorp Industries'}) RETURN count(u) AS total" 2>/dev/null | grep -o '"rows":\[\[[0-9]*\]\]' | grep -o '[0-9]*' || echo "0"

echo
if [ "$NODE_COUNT" -gt 0 ]; then
    echo "✓ Test fixture setup completed successfully!"
    echo "  - $NODE_COUNT nodes created"
    echo "  - $REL_COUNT relationships created"
    echo
    echo "The database is now populated with social network test data."
    echo "You can run tests that depend on this data."
    exit 0
else
    echo "⚠ WARNING: No nodes were created. Check execution above."
    exit 1
fi
